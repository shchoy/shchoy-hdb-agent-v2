"""Policy lineage extraction: Haiku reads policy, SOP, circular and precedent text and proposes SUPERSEDES,
OVERRIDES and APPLIES edges as structured output; every edge must carry the chunk and verbatim quote it was
read from. Controlled documents, clauses and precedents become nodes deterministically from the index metadata.

Nothing the model proposes is trusted: an edge whose evidence is not a verbatim span of a chunk of the document
it read, whose endpoints are unknown, or that the ontology doesn't allow, is dropped and reported. What survives
is written through `GraphWriter`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from typing import Any

from pydantic import BaseModel, ValidationError

from plg.agents.runtime import CACHE
from plg.entities.model import Edge, Node
from plg.entities.writer import GraphWriter
from plg.llm import Block, LLMClient
from plg.ontology import GENERATED
from plg.search.models import Chunk, DocumentMeta
from plg.search.store import SearchStore

NODE = "extract_lineage"
EDGE_TYPES = ("SUPERSEDES", "OVERRIDES", "APPLIES")
NODE_LABELS = {"policy": "Policy", "sop": "Sop", "template": "Template", "circular": "Circular"}
BATCH_CHUNKS = 25
"""Chunks per request; the precedent compendium is far longer than a policy."""

SYSTEM = """\
You read documents of the Properties & Land Group (PLG) and record how they relate, with the record_edges tool.

Edge types:
- SUPERSEDES: a later version of a policy, SOP, circular or template replaces an earlier one (source = newer).
- OVERRIDES: a circular replaces a clause of a policy version, possibly only for some units (source = circular, \
target = clause). Put who or what it is limited to in `scope`, e.g. "NC units only"; leave it out if unlimited.
- APPLIES: a precedent decision relied on a policy clause (source = precedent, target = clause).

Rules:
- Use only IDs from the lists you are given, exactly as written. If the clause or document is not listed, \
leave the edge out.
- Pick the policy version that was in force when the text says it applies; "clause 7.3 of PLG-POL-001 v3.0" is \
that version's clause 7.3.
- Every edge needs evidence_chunk_id (the chunk it is read from) and evidence_quote (a span of that chunk, copied \
character for character).
- Record only what the text states. If it states no such relation, record no edges."""


class ProposedEdge(BaseModel):
    type: str
    source_id: str
    source_label: str
    target_id: str
    target_label: str
    evidence_chunk_id: str
    evidence_quote: str
    scope: str | None = None


class Proposal(BaseModel):
    edges: list[ProposedEdge]


@cache
def record_edges_tool() -> Block:
    """Input schema: one `edges` array whose items may be any of the generated per-type edge shapes."""
    schemas = {t: json.loads((GENERATED / "extraction" / f"{t.lower()}.json").read_text()) for t in EDGE_TYPES}
    item: dict[str, object] = {"type": "object", "required": [], "properties": {}}
    properties: dict[str, object] = {}
    for t, schema in schemas.items():
        for key, value in schema["properties"]["edges"]["items"]["properties"].items():
            if key not in {"type", "source_label", "target_label"}:
                properties[key] = value
    properties["type"] = {"enum": list(EDGE_TYPES)}
    properties["source_label"] = {"enum": sorted({v for s in schemas.values() for v in _labels(s, "source_label")})}
    properties["target_label"] = {"enum": sorted({v for s in schemas.values() for v in _labels(s, "target_label")})}
    item.update(
        properties=properties,
        required=["type", "source_id", "source_label", "target_id", "target_label", "evidence_chunk_id", "evidence_quote"],
        additionalProperties=False,
    )
    return {
        "name": "record_edges",
        "description": "Record the relations the document states.",
        "input_schema": {
            "type": "object", "properties": {"edges": {"type": "array", "items": item}}, "required": ["edges"],
        },
    }


def _labels(schema: dict[str, Any], key: str) -> list[str]:
    return list(schema["properties"]["edges"]["items"]["properties"][key]["enum"])


@cache
def _allowed_labels(edge_type: str, key: str) -> frozenset[str]:
    schema = json.loads((GENERATED / "extraction" / f"{edge_type.lower()}.json").read_text())
    return frozenset(_labels(schema, key))


# ---------------------------------------------------------------- nodes from the index

_CLAUSE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_CIRCULAR = re.compile(r"Circular[ _](\d{2})[-/](\d{4})", re.I)
_PRECEDENT = re.compile(r"^(PC-\d{4}-\d{3}) - (.+)$")


def circular_id(doc: DocumentMeta) -> str | None:
    m = _CIRCULAR.search(f"{doc.title} {doc.source_path}")
    return f"Circular {m[1]}/{m[2]}" if m else None


def version_id(doc: DocumentMeta) -> str | None:
    return f"{doc.policy_id} v{doc.version}" if doc.policy_id and doc.version else None


def document_node(doc: DocumentMeta) -> Node | None:
    label = NODE_LABELS.get(doc.doc_type)
    if label is None:
        return None
    node_id = circular_id(doc) if label == "Circular" else version_id(doc)
    if node_id is None:
        return None
    props: dict[str, str | int | float | bool] = {"title": doc.title, "doc_id": doc.doc_id, "status": doc.status}
    if doc.policy_id and doc.version:
        props.update(policy_id=doc.policy_id, version=doc.version)
    if doc.effective_from:
        props["effective_from"] = doc.effective_from.isoformat()
    if doc.effective_to:
        props["effective_to"] = doc.effective_to.isoformat()
    return Node(id=node_id, label=label, name=node_id, props=props)


def clause_nodes(doc: DocumentMeta, chunks: Sequence[Chunk]) -> list[Node]:
    """One node per numbered section of a policy version, e.g. `PLG-POL-001 v3.0 cl. 7.3`."""
    owner = version_id(doc)
    if doc.doc_type != "policy" or owner is None:
        return []
    texts: dict[str, tuple[str, list[str]]] = {}
    for chunk in chunks:
        heading = re.sub(r" \(part \d+ of \d+\)$", "", chunk.location.split(" > ")[-1])
        if m := _CLAUSE.match(heading):
            texts.setdefault(m[1], (m[2], []))[1].append(chunk.text)
    return [
        Node(
            id=f"{owner} cl. {number}", label="Clause", name=f"{owner} cl. {number}: {title}",
            props={"clause_number": number, "text": " ".join(parts)[:500], "policy_id": doc.policy_id or "",
                   "version": doc.version or "", "doc_id": doc.doc_id},
        )
        for number, (title, parts) in texts.items()
    ]


_PAGE = re.compile(r" \(p\. \d+\)$")
_FIELDS = {
    "Date of decision": "decided_on", "Category": "category", "Town": "town", "Facts": "facts",
    "Decision": "decision", "Reasoning and policy basis": "reasoning", "Outcome / lessons": "outcome",
}
"""Rows of a compendium case table, as they read in the chunk text, and the property each becomes."""


def case_fields(text: str) -> dict[str, str]:
    """The case table of a compendium chunk: one value per row label, lines rejoined."""
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if line in _FIELDS:
            current = _FIELDS[line]
            fields.setdefault(current, [])
        elif current and line and line not in {"Item", "Detail"}:
            fields[current].append(line)
    joined = {k: " ".join(v) for k, v in fields.items()}
    if decided := joined.get("decided_on"):
        try:
            joined["decided_on"] = datetime.strptime(decided, "%d %B %Y").date().isoformat()
        except ValueError:
            del joined["decided_on"]
    return joined


def precedent_nodes(doc: DocumentMeta, chunks: Sequence[Chunk]) -> list[Node]:
    """One node per compendium case, holding the case as its page states it and the chunk it was read from."""
    if doc.doc_type != "precedent_compendium":
        return []
    texts: dict[str, list[Chunk]] = {}
    names: dict[str, str] = {}
    for chunk in sorted(chunks, key=lambda c: c.seq):
        if m := _PRECEDENT.match(chunk.location.split(" > ")[0]):
            texts.setdefault(m[1], []).append(chunk)
            names.setdefault(m[1], _PAGE.sub("", m[2]))
    nodes = []
    for case_id, parts in texts.items():
        props: dict[str, str | int | float | bool] = {
            "doc_id": doc.doc_id, "chunk_id": parts[0].chunk_id, "location": parts[0].location,
            **case_fields("\n".join(c.text for c in parts)),
        }
        nodes.append(Node(id=case_id, label="Precedent", name=f"{case_id} {names[case_id]}", props=props))
    return nodes


def precedent_edges(precedents: Sequence[Node], chunks: Sequence[Chunk], known: Callable[[str], bool]) -> list[Edge]:
    """CONCERNS_TRADE to every trade a case's chunks are tagged with, IN_NC to its NC when it names exactly one."""
    edges = []
    for node in precedents:
        own = [c for c in chunks if node.id in c.entity_ids and c.location.startswith(node.id)]
        trades = dict.fromkeys(t for c in own for t in c.trade)
        ncs = dict.fromkeys(n for c in own for n in c.nc)
        edges += [Edge(type="CONCERNS_TRADE", start=node.id, end=t) for t in trades if known(t)]
        if len(ncs) == 1 and known(nc := next(iter(ncs))):
            edges.append(Edge(type="IN_NC", start=node.id, end=nc))
    return edges


def has_clause_edges(clauses: Sequence[Node], policy_node_id: str) -> list[Edge]:
    return [Edge(type="HAS_CLAUSE", start=policy_node_id, end=c.id) for c in clauses]


# ---------------------------------------------------------------- extraction

def prompt(doc: DocumentMeta, chunks: Sequence[Chunk], nodes: Sequence[Node]) -> str:
    """The request for one batch of a document's chunks."""
    known = "\n".join(f"- {n.id} ({n.label})" for n in nodes if n.label in {*NODE_LABELS.values(), "Clause", "Precedent"})
    body = "\n\n".join(f"<chunk id=\"{c.chunk_id}\" location=\"{c.location}\">\n{c.text}\n</chunk>" for c in chunks)
    own = document_node(doc)
    return (
        f"Document: {doc.title} (source node: {own.id if own else doc.doc_id}).\n\n"
        f"Known IDs:\n{known}\n\nDocument text:\n{body}\n\nRecord the relations this text states."
    )


def _squash(text: str) -> str:
    return " ".join(text.split())


def validate(proposed: ProposedEdge, chunks: dict[str, Chunk], nodes: dict[str, Node]) -> tuple[Edge | None, str | None]:
    """The edge to write, or why it was dropped."""
    label = f"{proposed.type} {proposed.source_id} -> {proposed.target_id}"
    if proposed.type not in EDGE_TYPES:
        return None, f"{label}: unknown edge type"
    chunk = chunks.get(proposed.evidence_chunk_id)
    if chunk is None:
        return None, f"{label}: evidence chunk {proposed.evidence_chunk_id!r} is not in the document"
    quote = _squash(proposed.evidence_quote)
    if not quote or quote not in _squash(chunk.text):
        return None, f"{label}: evidence quote is not a verbatim span of {chunk.chunk_id}"
    for key, node_id, stated in (("source_label", proposed.source_id, proposed.source_label),
                                 ("target_label", proposed.target_id, proposed.target_label)):
        node = nodes.get(node_id)
        if node is None:
            return None, f"{label}: {node_id!r} is not a known node"
        if node.label != stated or stated not in _allowed_labels(proposed.type, key):
            return None, f"{label}: {node_id} is a {node.label}, not allowed here"
    props: dict[str, str | int | float | bool] = {
        "evidence_chunk_id": chunk.chunk_id, "evidence_quote": proposed.evidence_quote,
    }
    if proposed.scope:
        props["scope"] = proposed.scope
    return Edge(type=proposed.type, start=proposed.source_id, end=proposed.target_id, props=props), None


@dataclass
class LineageReport:
    nodes: int = 0
    edges: int = 0
    dropped: list[str] = field(default_factory=list)
    """Edges Haiku proposed that failed validation, with the reason."""


async def extract_lineage(llm: LLMClient, store: SearchStore, writer: GraphWriter) -> LineageReport:
    """Build the lineage layer of the graph from the indexed corpus. Safe to repeat: known nodes and edges are kept."""
    report = LineageReport()
    docs = store.documents()
    chunks_of = {d.doc_id: store.chunks(d.doc_id) for d in docs}
    nodes: dict[str, Node] = {}
    structural: list[Edge] = []
    sources: list[DocumentMeta] = []
    for doc in docs:
        found = [n for n in (document_node(doc),) if n]
        clauses = clause_nodes(doc, chunks_of[doc.doc_id])
        precedents = precedent_nodes(doc, chunks_of[doc.doc_id])
        if found:
            structural += has_clause_edges(clauses, found[0].id)
        structural += precedent_edges(precedents, chunks_of[doc.doc_id], lambda i: writer.store.node(i) is not None)
        if found or precedents:
            sources.append(doc)
        nodes.update((n.id, n) for n in [*found, *clauses, *precedents])

    proposals: list[Edge] = []
    for doc in sources:
        chunks = chunks_of[doc.doc_id]
        for start in range(0, len(chunks), BATCH_CHUNKS):
            batch = chunks[start:start + BATCH_CHUNKS]
            by_id = {c.chunk_id: c for c in batch}
            reply = await llm.complete(
                node=NODE, tier="haiku", system=[{"type": "text", "text": SYSTEM, "cache_control": CACHE}],
                messages=[{"role": "user", "content": prompt(doc, batch, list(nodes.values()))}],
                tools=[record_edges_tool()], tool_choice={"type": "tool", "name": "record_edges"},
            )
            call = next((b for b in reply.content if b["type"] == "tool_use"), None)
            if call is None:
                continue
            try:
                proposal = Proposal.model_validate(call["input"])
            except ValidationError as exc:
                report.dropped.append(f"{doc.title}: unreadable reply ({exc.errors()[0]['msg']})")
                continue
            for edge in proposal.edges:
                accepted, why = validate(edge, by_id, nodes)
                if accepted:
                    proposals.append(accepted)
                elif why:
                    report.dropped.append(why)

    fresh = [n for n in nodes.values() if writer.store.node(n.id) is None]
    writer.write(fresh, [*structural, *proposals])
    report.nodes, report.edges = len(fresh), len(proposals)
    return report
