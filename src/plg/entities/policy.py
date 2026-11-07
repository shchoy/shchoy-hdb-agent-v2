"""Policy lineage: the versions of one controlled document, what superseded what, and the circulars that
override its clauses. Read from SUPERSEDES / OVERRIDES edges, each carrying the evidence it was read from."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from plg.entities.model import Edge, Node


class PolicyVersion(BaseModel):
    id: str
    """Node ID, e.g. `PLG-POL-003 v2.0`."""
    label: str
    """`Policy`, `Sop` or `Template`."""
    title: str
    version: str
    doc_id: str
    effective_from: date | None = None
    effective_to: date | None = None
    status: Literal["current", "superseded"]


class Supersession(BaseModel):
    newer: str
    older: str
    evidence_chunk_id: str
    evidence_quote: str


class Override(BaseModel):
    """A circular that replaces a clause of one version, possibly only for some units."""

    circular_id: str
    circular_title: str
    circular_doc_id: str
    clause_id: str
    clause_number: str
    policy_version: str
    effective_from: date | None = None
    effective_to: date | None = None
    scope: str | None = None
    evidence_chunk_id: str
    evidence_quote: str


class PolicyLineage(BaseModel):
    policy_id: str
    title: str
    current: str | None
    """ID of the version in force today, if any."""
    versions: list[PolicyVersion]
    """Oldest first."""
    supersessions: list[Supersession]
    overrides: list[Override]


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def as_date(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def policy_version(node: Node) -> PolicyVersion:
    p = node.props
    return PolicyVersion(
        id=node.id, label=node.label, title=str(p.get("title", node.name)), version=str(p.get("version", "")),
        doc_id=str(p.get("doc_id", "")), effective_from=as_date(p.get("effective_from")),
        effective_to=as_date(p.get("effective_to")), status="superseded" if p.get("status") == "superseded" else "current",
    )


def supersession(edge: Edge) -> Supersession:
    return Supersession(
        newer=edge.start, older=edge.end, evidence_chunk_id=str(edge.props.get("evidence_chunk_id", "")),
        evidence_quote=str(edge.props.get("evidence_quote", "")),
    )


def override(edge: Edge, circular: Node, clause: Node) -> Override:
    p = circular.props
    return Override(
        circular_id=circular.id, circular_title=str(p.get("title", circular.name)),
        circular_doc_id=str(p.get("doc_id", "")), clause_id=clause.id,
        clause_number=str(clause.props.get("clause_number", "")), policy_version=str(clause.props.get("version", "")),
        effective_from=as_date(p.get("effective_from")), effective_to=as_date(p.get("effective_to")),
        scope=str(edge.props["scope"]) if edge.props.get("scope") else None,
        evidence_chunk_id=str(edge.props.get("evidence_chunk_id", "")),
        evidence_quote=str(edge.props.get("evidence_quote", "")),
    )


def in_force(v: PolicyVersion, on: date) -> bool:
    return (v.effective_from is None or v.effective_from <= on) and (v.effective_to is None or on <= v.effective_to)


def build_lineage(
    policy_id: str, versions: list[Node], edges: list[Edge], circulars: dict[str, Node], clauses: dict[str, Node],
    as_of: date | None = None,
) -> PolicyLineage:
    ordered = sorted((policy_version(n) for n in versions), key=lambda v: version_key(v.version))
    if as_of:  # the card and the passage read "current" from the status: restate it for that date
        ordered = [v.model_copy(update={"status": "current" if in_force(v, as_of) else "superseded"}) for v in ordered]
    ids = {v.id for v in ordered}
    # With a date, "current" is the version in force then; otherwise the one in force today.
    current = [v for v in ordered if v.status == "current"]
    return PolicyLineage(
        policy_id=policy_id,
        title=(current or ordered)[-1].title,
        current=current[-1].id if current else None,
        versions=ordered,
        supersessions=[supersession(e) for e in edges if e.type == "SUPERSEDES" and e.start in ids and e.end in ids],
        overrides=sorted(
            (override(e, circulars[e.start], clauses[e.end]) for e in edges if e.type == "OVERRIDES" and e.end in clauses),
            key=lambda o: (o.clause_id, o.effective_from or date.min),
        ),
    )
