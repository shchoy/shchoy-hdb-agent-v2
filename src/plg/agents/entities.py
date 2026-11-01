"""The knowledge agent's graph tools: read-only lookups in the entity graph.

`resolve_entities` turns a name, unit number or ID into entity IDs. `entity_context` returns what surrounds an
entity as citable record passages (one per entity, a sentence per fact or relationship), so answers drawn from
PLG Records carry citations like any document. `policy_lineage` does the same for a controlled document: its
versions, what superseded what and the circulars overriding its clauses, each with the evidence it was read from.
Claude never writes a graph query, and no tool writes the graph.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel

from plg.agents.runtime import Source, Tool
from plg.entities.cypher import HUB_LABELS, MAX_HOPS
from plg.entities.model import Edge, Node
from plg.entities.policy import PolicyLineage
from plg.entities.store import EntityContext, GraphStore
from plg.search.models import Chunk

MAX_RECORDS = 60
"""Entities shown per context; the ones nearest the root come first."""


class ResolveInput(BaseModel):
    text: str
    labels: list[str] | None = None


class ContextInput(BaseModel):
    entity_id: str
    hops: int = MAX_HOPS


def _fact(name: str, value: object) -> str:
    return f"{name.replace('_', ' ')}: {value}."


def _edge_sentence(edge: Edge, names: dict[str, Node]) -> str:
    def ref(node_id: str) -> str:
        node = names[node_id]
        return f"{node.label} {node.name} ({node.id})" if node.name != node.id else f"{node.label} {node.id}"

    return f"{ref(edge.start)} {edge.type.lower().replace('_', ' ')} {ref(edge.end)}."


def record_chunk(node: Node, edges: list[Edge], names: dict[str, Node]) -> Chunk:
    lines = [f"{node.label} {node.id}: {node.name}."]
    lines += [_fact(k, v) for k, v in node.props.items()]
    lines += [_edge_sentence(e, names) for e in edges]
    text = "\n".join(lines)
    return Chunk(
        doc_id=node.id, doc_type="record", title=f"PLG Records: {node.label} {node.name}",
        source_system="plg_records", source_path=f"plg_records/{node.id}",
        content_hash=hashlib.sha256(text.encode()).hexdigest(), chunk_id=f"record:{node.id}", seq=0, header="",
        text=text, location=f"{node.label} record", vector=[],
    )


def context_sources(context: EntityContext) -> list[Source]:
    names = {n.id: n for n in [context.root, *context.nodes]}
    touching: dict[str, list[Edge]] = {}
    for edge in context.edges:
        for end in (edge.start, edge.end):
            touching.setdefault(end, []).append(edge)
    adjacent = {context.root.id} | {e.end if e.start == context.root.id else e.start for e in touching.get(context.root.id, [])}
    shown = [n for n in [context.root, *context.nodes] if n.id == context.root.id or n.label not in HUB_LABELS]
    shown.sort(key=lambda n: (n.id != context.root.id, n.id not in adjacent))
    return [
        Source(chunk := record_chunk(n, touching.get(n.id, []), names), chunk.title) for n in shown[:MAX_RECORDS]
    ]


class LineageInput(BaseModel):
    policy_id: str
    as_of: date | None = None


def _period(start: object, end: object) -> str:
    if start and end:
        return f"{start} to {end}"
    return f"from {start}" if start else "(no effective date recorded)"


def lineage_chunk(found: PolicyLineage) -> Chunk:
    """The lineage as one citable passage, a sentence per fact; evidence quotes are part of the sentence."""
    lines = [f"{found.policy_id} {found.title} has {len(found.versions)} version(s)."]
    for v in reversed(found.versions):
        state = "the current version" if v.status == "current" else "superseded"
        lines.append(f"{v.id} is {state}, in force {_period(v.effective_from, v.effective_to)}.")
    for s in found.supersessions:
        lines.append(f'{s.newer} supersedes {s.older}: "{s.evidence_quote}".')
    for o in found.overrides:
        limit = f" for {o.scope}" if o.scope else ""
        lines.append(
            f"{o.circular_id} (effective {_period(o.effective_from, o.effective_to)}) overrides clause "
            f"{o.clause_number} of {found.policy_id} "
            f'v{o.policy_version}{limit}: "{o.evidence_quote}".'
        )
        if o.scope:
            lines.append(f"Clause {o.clause_number} of v{o.policy_version} still applies to everything outside {o.scope}.")
    text = "\n".join(lines)
    return Chunk(
        doc_id=found.policy_id, doc_type="record", title=f"Policy lineage: {found.policy_id} {found.title}",
        source_system="plg_records", source_path=f"plg_records/lineage/{found.policy_id}",
        content_hash=hashlib.sha256(text.encode()).hexdigest(), chunk_id=f"lineage:{found.policy_id}", seq=0,
        header="", text=text, location="Policy lineage", vector=[],
    )


def lineage_tool(graph: GraphStore, on_lineage: Callable[[PolicyLineage], None] | None = None) -> Tool:
    async def run(raw: dict[str, Any]) -> str | list[Source]:
        args = LineageInput.model_validate(raw)
        found = await asyncio.to_thread(graph.policy_lineage, args.policy_id, args.as_of)
        if found is None:
            return f"No controlled document has the ID {args.policy_id!r}. Search the corpus for it instead."
        if on_lineage:
            on_lineage(found)
        chunk = lineage_chunk(found)
        return [Source(chunk, chunk.title)]

    return Tool(
        name="policy_lineage",
        description=(
            "The lineage of one policy or SOP: every version with its effective dates, which version superseded "
            "which, and the circulars that override its clauses (and for which units). Use it for 'what is our "
            "current position on X', 'what changed' and 'what was the rule on <date>'. Takes the document ID, e.g. "
            "PLG-POL-003. Search the corpus for the clause wording itself."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "policy_id": {"type": "string", "description": "A policy or SOP ID such as PLG-POL-001."},
                "as_of": {
                    "type": "string", "format": "date",
                    "description": "For a question about an earlier date: the version in force then is marked current.",
                },
            },
            "required": ["policy_id"],
        },
        run=run,
    )


def entity_tools(graph: GraphStore, on_lineage: Callable[[PolicyLineage], None] | None = None) -> list[Tool]:
    async def resolve(raw: dict[str, Any]) -> str:
        args = ResolveInput.model_validate(raw)
        found = await asyncio.to_thread(graph.resolve_entities, args.text, args.labels)
        if not found:
            return "No entity matches. Try other words, or search the documents."
        return "\n".join(f"{e.id} | {e.label} | {e.name}" for e in found)

    async def context(raw: dict[str, Any]) -> str | list[Source]:
        args = ContextInput.model_validate(raw)
        found = await asyncio.to_thread(graph.entity_context, args.entity_id, args.hops)
        if found is None:
            return f"No entity has the ID {args.entity_id!r}. Use resolve_entities to find it."
        return context_sources(found)

    return [
        Tool(
            name="resolve_entities",
            description=(
                "Find PLG Records entities (tenants, units, tenancies, blocks, letters, tickets, ...) by name, "
                "unit number or business ID, e.g. 'Golden Leaf', '#01-32 Blk 214', 'TA-2024-00542'. Returns "
                "`id | type | name` lines, best match first. Several close matches mean the name is ambiguous."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "A name, unit number or ID, not a whole question."},
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Only these entity types."},
                },
                "required": ["text"],
            },
            run=resolve,
        ),
        Tool(
            name="entity_context",
            description=(
                "What PLG Records hold around one entity within 1-2 relationships, as citable passages: a tenant's "
                "tenancies, units and letters; a unit's tenancies, feedback, tickets, inspections and tasks; and the "
                "staff who worked on them. Facts and relationships only, no totals. Call it again on a related "
                "entity (e.g. the unit of a tenancy) to go further."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "An ID from resolve_entities."},
                    "hops": {"type": "integer", "enum": list(range(1, MAX_HOPS + 1)), "description": "Default 2."},
                },
                "required": ["entity_id"],
            },
            run=context,
        ),
        lineage_tool(graph, on_lineage),
    ]
