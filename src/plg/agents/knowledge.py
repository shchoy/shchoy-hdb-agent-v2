"""The `knowledge` agent: answers policy and records questions from the indexed corpus, citing every claim.

Its only tool is read-only hybrid search. Searches default to documents in force today, so a superseded
policy version is never shown unless Claude asks what applied on an earlier date. PLG terms and
abbreviations in the question are resolved through the vocabulary index and added to each search query.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from pydantic import BaseModel

from plg.agents.entities import entity_tools
from plg.agents.runtime import AgentResult, Source, Tool, run_agent
from plg.entities.store import GraphStore
from plg.llm import AgentMessage, LLMClient
from plg.ontology.vocab import TermMatch, VocabIndex
from plg.search.models import SearchFilter, SearchHit
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
- Give PLG's current stance: the version in force, its effective date, and what it superseded when the \
sources say so. Searches return documents in force today unless you set `as_of` to ask about an earlier date.
- If another document (an SOP, guide, FAQ or email) contradicts the current policy, say which one and that \
the policy prevails.
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
) -> AgentResult:
    doc_types = [c.notation for c in vocab.scheme("plg:document_types") if c.notation]
    return await run_agent(
        llm,
        node=NODE,
        system=SYSTEM,
        context=describe_terms(vocab.find_terms(question)),
        tools=[search_tool(retriever, vocab, doc_types), *(entity_tools(entities) if entities else [])],
        messages=messages,
    )
