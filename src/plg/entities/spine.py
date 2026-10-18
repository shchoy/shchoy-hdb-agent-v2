"""The deterministic entity spine: PLG Records rows become typed nodes and edges, with no model involved.

Every business ID is checked against its strict format; a row with a malformed ID, or an edge the ontology
allow-list doesn't permit, is skipped and reported rather than loaded. The result is written as Neptune
openCypher bulk-load CSVs (`csvio`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plg.entities.allow import AllowList, load_allow_list
from plg.entities.csvio import write_graph
from plg.entities.ids import is_valid_id, label_for_id
from plg.entities.model import Edge, GraphData, Node, Scalar
from plg.ontology.vocab import VocabIndex, load_vocab


@dataclass
class SpineBuild:
    data: GraphData = field(default_factory=GraphData)
    skipped: list[str] = field(default_factory=list)


class _Builder:
    def __init__(self, allow: AllowList) -> None:
        self.allow = allow
        self.build = SpineBuild()
        self._pending: list[Edge] = []

    def node(self, label: str, node_id: str | None, name: str | None, **props: Scalar | None) -> None:
        if label not in self.allow.node_labels:
            raise ValueError(f"{label} is not an ontology node label")
        if not node_id or not is_valid_id(label, node_id):
            self.build.skipped.append(f"{label} with malformed ID {node_id!r}")
            return
        clean = {k: v for k, v in props.items() if v is not None and v != ""}
        self.build.data.add_node(Node(id=node_id, label=label, name=name or node_id, props=clean))

    def edge(self, edge_type: str, start: str | None, end: str | None) -> None:
        if start and end:
            self._pending.append(Edge(type=edge_type, start=start, end=end))

    def finish(self) -> SpineBuild:
        nodes = self.build.data.nodes
        for edge in self._pending:
            if edge.start not in nodes or edge.end not in nodes:
                self.build.skipped.append(f"{edge.id}: endpoint missing")
            elif not self.allow.permits_edge(edge.type, nodes[edge.start].label, nodes[edge.end].label):
                self.build.skipped.append(f"{edge.id}: not in the allow-list")
            else:
                self.build.data.add_edge(edge)
        return self.build


def _rows(db: sqlite3.Connection, table: str) -> Iterator[dict[str, Any]]:
    db.row_factory = sqlite3.Row
    for row in db.execute(f"SELECT * FROM {table}"):  # noqa: S608 - table names are literals below
        yield dict(row)


def build_spine(records_db: Path, vocab: VocabIndex | None = None, allow: AllowList | None = None) -> SpineBuild:
    vocab = vocab or load_vocab()
    b = _Builder(allow or load_allow_list())
    categories = {c.notation: c.pref_label for c in vocab.scheme("plg:defect_categories") if c.notation}
    db = sqlite3.connect(f"file:{records_db}?mode=ro", uri=True)
    try:
        blocks: dict[str, dict[str, Any]] = {}
        units: dict[str, str] = {}
        letter_refs: set[str] = set()
        for r in _rows(db, "staff"):
            b.node("Staff", r["staff_id"], r["name"], title=r["title"], dept=r["dept"])
        for r in _rows(db, "towns"):
            b.node("Town", r["town_code"], r["town_name"], region=r["region"], town_council=r["town_council"])
        for r in _rows(db, "neighbourhood_centres"):
            b.node("NeighbourhoodCentre", r["nc_id"], r["nc_name"])
            b.edge("IN_TOWN", r["nc_id"], r["town_code"])
        for r in _rows(db, "blocks"):
            blocks[r["block_id"]] = r
            b.node("Block", r["block_id"], f"Blk {r['blk']} {r['street']}",
                   postal_code=r["postal_code"], year_built=r["year_built"])
            b.edge("IN_NC", r["block_id"], r["nc_id"])
        for r in _rows(db, "trades"):
            b.node("Trade", r["trade"], r["trade"], trade_group=r["trade_group"])
        for r in _rows(db, "units"):
            blk = blocks.get(r["block_id"])
            units[r["unit_id"]] = name = f"Blk {blk['blk']} {blk['street']} {r['unit_no']}" if blk else r["unit_id"]
            b.node("Unit", r["unit_id"], name, unit_type=r["unit_type"], unit_status=r["status"],
                   floor_area_sqm=r["floor_area_sqm"], vacant_since=r["vacant_since"])
            b.edge("IN_BLOCK", r["unit_id"], r["block_id"])
        for r in _rows(db, "tenants"):
            b.node("Tenant", r["tenant_id"], r["name"], uen=r["brn"], entity_type=r["entity_type"],
                   contact_person=r["contact_person"], registered_since=r["registered_since"])
        for r in _rows(db, "tenancies"):
            b.node("Tenancy", r["tenancy_id"], f"Tenancy {r['tenancy_id']}", tenancy_status=r["status"],
                   start_date=r["start_date"], end_date=r["end_date"], monthly_rent=r["monthly_rent"],
                   rent_basis=r["rent_basis"])
            b.edge("OF_UNIT", r["tenancy_id"], r["unit_id"])
            b.edge("HELD_BY", r["tenancy_id"], r["tenant_id"])
            b.edge("FOR_TRADE", r["tenancy_id"], r["trade"])
        for r in _rows(db, "letters"):
            if r["reference_id"] and label_for_id(r["reference_id"]) == "RentInvoice":
                letter_refs.add(r["reference_id"])
        # Invoices are many and routine: only those a letter was issued for are entities worth a node.
        for r in _rows(db, "rent_invoices"):
            if r["invoice_id"] in letter_refs:
                b.node("RentInvoice", r["invoice_id"], f"Invoice {r['invoice_id']}", due_date=r["due_date"],
                       amount=r["total_amount"], invoice_status=r["status"], period=r["period"])
                b.edge("BILLED_TO", r["invoice_id"], r["tenancy_id"])
        for r in _rows(db, "inspections"):
            b.node("Inspection", r["inspection_id"], f"Inspection {r['inspection_id']}",
                   inspection_date=r["inspection_date"], inspection_type=r["inspection_type"],
                   finding_code=r["finding_code"], outcome=r["outcome"], remarks=r["remarks"],
                   closed_date=r["closed_date"])
            b.edge("INSPECTED", r["inspection_id"], r["unit_id"])
            b.edge("INSPECTED_BY", r["inspection_id"], r["officer_id"])
            b.edge("WORKED_ON", r["officer_id"], r["inspection_id"])
        for code, label in categories.items():
            b.node("DefectCategory", code, label)
        for r in _rows(db, "feedback_cases"):
            b.node("FeedbackCase", r["feedback_id"], f"Feedback {r['feedback_id']}", received_date=r["received_date"],
                   channel=r["channel"], description=r["description"], severity=r["severity"],
                   feedback_status=r["status"], reply_due=r["reply_due"], replied_date=r["replied_date"])
            b.edge("ABOUT_UNIT", r["feedback_id"], r["unit_id"])
            b.edge("IN_CATEGORY", r["feedback_id"], r["category_code"])
            b.edge("RAISED", r["feedback_id"], r["iems_ticket_id"])
            b.edge("WORKED_ON", r["officer_id"], r["feedback_id"])
        teams: set[str] = set()
        vendors: set[str] = set()
        for r in _rows(db, "iems_tickets"):
            b.node("IemsTicket", r["ticket_id"], f"Ticket {r['ticket_id']}", created_date=r["created_date"],
                   severity=r["priority"], ticket_status=r["status"], sla_days=r["sla_days"],
                   completed_date=r["completed_date"])
            b.edge("IN_CATEGORY", r["ticket_id"], r["category_code"])
            for kind, value, edge_type, seen in (
                ("Team", r["team"], "ROUTED_TO", teams), ("Vendor", r["vendor"], "SERVICED_BY", vendors)
            ):
                if value:
                    if value not in seen:
                        seen.add(value)
                        b.node(kind, value, value)
                    b.edge(edge_type, r["ticket_id"], value)
        for r in _rows(db, "applications"):
            b.node("Application", r["application_id"], f"Application {r['application_id']}", app_type=r["app_type"],
                   submitted_date=r["submitted_date"], application_status=r["status"],
                   decision_date=r["decision_date"], remarks=r["remarks"])
            b.edge("APPLIED_BY", r["application_id"], r["tenant_id"])
            b.edge("FOR_UNIT", r["application_id"], r["unit_id"])
            b.edge("PROPOSES_TRADE", r["application_id"], r["proposed_trade"])
            b.edge("WORKED_ON", r["officer_id"], r["application_id"])
        for r in _rows(db, "tasks"):
            b.node("Task", r["task_id"], r["title"] or f"Task {r['task_id']}", task_type=r["task_type"],
                   due_date=r["due_date"], task_status=r["status"], safety_flag=bool(r["safety_flag"]))
            b.edge("ASSIGNED_TO", r["task_id"], r["assignee_id"])
            b.edge("CONCERNS", r["task_id"], r["related_id"])
        for r in _rows(db, "letters"):
            b.node("Letter", r["letter_id"], f"{r['letter_type']} {r['letter_id']}", letter_type=r["letter_type"],
                   letter_date=r["letter_date"], channel=r["channel"])
            b.edge("ISSUED_FOR", r["letter_id"], r["reference_id"])
            b.edge("ADDRESSED_TO", r["letter_id"], r["tenant_id"])
            b.edge("WORKED_ON", r["author_id"], r["letter_id"])
    finally:
        db.close()
    return b.finish()


def write_spine(records_db: Path, out: Path) -> SpineBuild:
    """Build the spine and write its CSVs to `out`, replacing any earlier spine files there."""
    build = build_spine(records_db)
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("nodes_*.csv"), *out.glob("edges.csv")]:
        old.unlink()
    write_graph(out, build.data)
    return build
