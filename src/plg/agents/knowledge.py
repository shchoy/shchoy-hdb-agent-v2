"""The `knowledge` agent: answers policy and records questions from the indexed corpus, citing every claim.

Its only tool is read-only hybrid search. Searches default to documents in force today, so a superseded
policy version is never shown unless Claude asks what applied on an earlier date. PLG terms and
abbreviations in the question are resolved through the vocabulary index and added to each search query.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel

from plg.agents.entities import entity_tools, precedent_tool
from plg.agents.glossary import definitions_tool
from plg.agents.runtime import AgentResult, Source, Tool, run_agent
from plg.entities.policy import PolicyLineage
from plg.entities.store import GraphStore
from plg.guardrails.injection import InjectionFlag
from plg.llm import AgentMessage, LLMClient
from plg.ontology.vocab import TermMatch, VocabIndex
from plg.search.models import SearchFilter, SearchHit
from plg.ontology.glossary import Glossary
from plg.search.rerank import Retriever

NODE = "knowledge"

SYSTEM = """\
You are the knowledge specialist of the PLG Super-Librarian, answering officers of the Properties & Land Group \
from PLG's own documents: policies, SOPs, circulars, guides, FAQs, emails, notes and reports.

Rules:
- Search before answering. Search again with other words if the first results miss the point.
- Answer only from the search results and records you were shown, and cite every factual claim.
- For a question about a tenant, unit or tenancy ("tell me about Golden Leaf", "what's on TA-2024-00542"), call \
resolve_entities with the name, unit number or ID, then entity_context on the match. A tenant's context shows its \
tenancies and letters; call entity_context on its unit as well for feedback, tickets and inspections. If several \
entities match a name closely, say so and name them rather than guessing.
- For what a PLG business term means (vacant, arrears, occupancy rate, LOD trigger, ...), call \
glossary_definitions with the term. It lists every approved version with its effective dates and source: give the \
definition in force now and, when asked about an earlier date or period, the version then in force, citing both.
- Give PLG's current stance: the version in force, its effective date, and what it superseded when the \
sources say so. Searches return documents in force today unless you set `as_of` to ask about an earlier date.
- For a policy topic, call policy_lineage with the policy's ID (find it by searching if you don't know it). It lists \
the versions with effective dates, what superseded what and the circulars overriding clauses, and for which \
units. Where a circular overrides a clause only for some units (e.g. NC units), state the rule for each kind of \
unit and the date it took effect; the original clause still governs the rest. For "what was the rule on <date>", \
search with `as_of` set to that date and use the lineage to name the version then in force.
- For a precedent question ("any precedent for...", "what did we do before when..."), call find_precedents with \
the trade, the NC (ID or name) and the issue, e.g. "change of trade" or "fire rent rebate". For each precedent that \
bears on the case, give its decision and reasoning, cite its compendium page or the email discussing it, and say \
(after searching for the facts of the officer's own case, e.g. its incident report or emails) how the officer's case differs from it (another NC, a different outlet count, a fire the tenant caused where the \
precedent's was not) and so whether it fits. Precedents guide decisions but do not bind them; the policy in force \
prevails.
- If another document (an SOP, guide, FAQ, training deck or email) contradicts the current policy or circular \
(an older figure, deadline or period), say which document, what it says, and that the policy prevails. Check the \
other documents your searches return against the current position before you answer.
- If the results don't answer the question, say plainly that the indexed sources don't cover it. Never \
answer from general knowledge.
- Be concise and use PLG's own terms."""


class SearchInput(BaseModel):
    query: str
    as_of: date | None = None
    doc_types: list[str] | None = None


def describe_terms(terms: list[TermMatch]) -> str:
    """The PLG terms spotted in the question, for the agent's context."""
    if not terms:
        return ""
    lines = [
        f'- "{t.text}" means ' + "; ".join(f"{c.pref_label} ({c.id})" for c in t.concepts) for t in terms
    ]
    return "PLG terms in the question:\n" + "\n".join(lines)


def expand(query: str, vocab: VocabIndex) -> str:
    """The query with the preferred label of every PLG term in it, so "LOD" also matches "Letter of Demand"."""
    labels = dict.fromkeys(
        c.pref_label for t in vocab.find_terms(query) for c in t.concepts if c.pref_label.casefold() not in query.casefold()
    )
    return f"{query} ({'; '.join(labels)})" if labels else query


def title(hit: SearchHit) -> str:
    c = hit.chunk
    version = f" v{c.version}" if c.version and c.version not in c.title else ""
    period = f", effective {c.effective_from.isoformat()}" if c.effective_from else ""
    if c.effective_to:
        period += f" to {c.effective_to.isoformat()}"
    return f"{c.title}{version} ({c.doc_type}, {c.status}{period}) - {c.location}"


def search_tool(retriever: Retriever, vocab: VocabIndex, doc_types: list[str]) -> Tool:
    async def run(raw: dict[str, Any]) -> list[Source]:
        args = SearchInput.model_validate(raw)
        filters = SearchFilter(
            # In force on a date (superseded versions included); otherwise only what is current.
            in_force_on=args.as_of,
            status=None if args.as_of else "current",
            doc_type=args.doc_types or None,
        )
        hits = await asyncio.to_thread(retriever.search, expand(args.query, vocab), filters=filters)
        return [Source(h.chunk, title(h)) for h in hits]

    return Tool(
        name="search_corpus",
        description=(
            "Hybrid search of PLG's indexed documents. Returns the best-matching passages, each titled with "
            "its document, version, status, effective dates and section."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, in words."},
                "as_of": {
                    "type": "string", "format": "date",
                    "description": "Only documents in force on this date (YYYY-MM-DD). Omit for today.",
                },
                "doc_types": {
                    "type": "array", "items": {"type": "string", "enum": doc_types},
                    "description": "Only these document types.",
                },
            },
            "required": ["query"],
        },
        run=run,
    )


async def answer(
    llm: LLMClient,
    retriever: Retriever,
    vocab: VocabIndex,
    messages: list[AgentMessage],
    question: str,
    entities: GraphStore | None = None,
    on_lineage: Callable[[PolicyLineage], None] | None = None,
    on_injection: Callable[[InjectionFlag], None] | None = None,
    glossary: Callable[[], Glossary] | None = None,
) -> AgentResult:
    doc_types = [c.notation for c in vocab.scheme("plg:document_types") if c.notation]
    return await run_agent(
        llm,
        node=NODE,
        system=SYSTEM,
        context=describe_terms(vocab.find_terms(question)),
        tools=[
            search_tool(retriever, vocab, doc_types),
            *([definitions_tool(glossary)] if glossary else []),
            *([*entity_tools(entities, on_lineage), precedent_tool(entities, retriever)] if entities else []),
        ],
        messages=messages,
        on_injection=on_injection,
    )
