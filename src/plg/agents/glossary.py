"""Business glossary for the agents (issue #25).

`glossary_definitions` (the knowledge agent's tool) shows every approved version of a term as one citable passage,
`glossary:<concept>`: each version's dates, definition, value and source document, so "what does vacant mean now,
and what did it mean before" is answered and cited from one read.

`read_change` (node `glossary`, Sonnet, forced `propose_glossary_change`) reads an officer's request to change a
definition; actions/glossary.py checks it and makes the proposal. The tool only describes the change: nothing
changes until the term owner approves it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from plg.actions.glossary import ChangeRequest
from plg.agents.runtime import CACHE, Source, Tool
from plg.llm import AgentMessage, Block, LLMClient
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.glossary import Glossary
from plg.search.models import Chunk

NODE = "glossary"
PROPOSE = "propose_glossary_change"

SYSTEM = """\
You prepare changes to PLG's business glossary. The officer asks to change what a business term means (a new \
definition, threshold or value, from a date). Call propose_glossary_change once with:
- concept: the glossary term (its concept ID from the list below, or its label),
- definition: the complete new definition, written like the current one (not just the difference),
- value: the parameter the definition fixes, if any (e.g. "75 days", "includes units under tender"),
- effective_from: the date it takes effect, if the officer gave one,
- reason: why, in the officer's words (meeting, circular, decision),
- source: the document the change comes from, if the officer named one,
- sql: only if the officer gave the SQL that should compute the term from now on.
Nothing changes until the term owner approves the proposal.

Glossary terms in force:
{terms}"""

PROPOSE_TOOL: Block = {
    "name": PROPOSE,
    "description": "Propose a new version of a business term's definition, for its owner to approve.",
    "input_schema": {
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "The glossary concept ID (e.g. plg:Vacant) or label."},
            "definition": {"type": "string", "description": "The complete new definition."},
            "value": {"type": "string", "description": "The parameter the definition fixes, if any."},
            "effective_from": {"type": "string", "format": "date", "description": "When it takes effect (YYYY-MM-DD)."},
            "reason": {"type": "string", "description": "Why the definition changes."},
            "source": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"}, "locator": {"type": "string"}, "quote": {"type": "string"},
                },
                "description": "The document the change comes from, if named.",
            },
            "sql": {"type": "string", "description": "A new SQL binding (one SELECT using $as_of), only if given."},
        },
        "required": ["concept", "definition", "reason"],
    },
}


def terms_list(glossary: Glossary) -> str:
    lines = []
    for concept in glossary.concepts():
        if term := glossary.current(concept):
            lines.append(f"- {concept} ({term.pref_label}, {term.id}): {term.definition}")
    return "\n".join(lines)


async def read_change(llm: LLMClient, messages: list[AgentMessage], glossary: Glossary) -> ChangeRequest | str:
    """The change the officer asks for, or why it couldn't be read."""
    reply = await llm.complete(
        node=NODE,
        tier="sonnet",
        system=[{"type": "text", "text": SYSTEM.format(terms=terms_list(glossary)), "cache_control": CACHE}],
        messages=messages,
        tools=[PROPOSE_TOOL],
        tool_choice={"type": "tool", "name": PROPOSE},
    )
    call = next((b for b in reply.content if b["type"] == "tool_use"), None)
    if call is None:
        return "The change could not be read from the request: name the term, the new definition and the reason."
    try:
        return ChangeRequest.model_validate(call["input"])
    except ValidationError as e:
        return f"The change could not be read from the request: {e.errors()[0]['msg']}."


# ---------------------------------------------------------------- definitions for the knowledge agent


class DefinitionsInput(BaseModel):
    term: str


def _period(t: GlossaryTerm) -> str:
    start = f"from {t.effective_from}" if t.effective_from else "since before records began"
    return f"{start} to {t.effective_to}" if t.effective_to else start


def definitions_chunk(glossary: Glossary, concept: str) -> Chunk:
    """Every approved version of `concept`, newest first, a sentence per fact."""
    versions = [t for t in reversed(glossary.versions(concept)) if t.status != "proposed"]
    label = versions[0].pref_label if versions else concept
    lines = [f"{label} ({concept}) has {len(versions)} approved version(s) in the PLG business glossary."]
    for t in versions:
        state = "the current version" if t.status == "current" else "superseded"
        lines.append(f"{t.id} is {state}, in force {_period(t)}.")
        lines.append(f"{t.id} definition: {t.definition}")
        if t.value:
            lines.append(f"{t.id} value: {t.value}.")
        where = ", ".join(p for p in (t.source.document_id, t.source.locator) if p)
        quote = f': "{t.source.quote.strip()}"' if t.source.quote else ""
        if where:
            lines.append(f"{t.id} source: {where}{quote}.")
    if versions:
        lines.append(f"Term owner: {versions[0].owned_by}.")
    text = "\n".join(lines)
    return Chunk(
        doc_id=concept, doc_type="record", title=f"Glossary: {label}", source_system="plg_records",
        source_path=f"plg_records/glossary/{concept}", content_hash=hashlib.sha256(text.encode()).hexdigest(),
        chunk_id=f"glossary:{concept}", seq=0, header="", text=text, location="PLG business glossary", vector=[],
    )


def definitions_tool(glossary: Callable[[], Glossary]) -> Tool:
    """`glossary` is read on every call, so approved changes show at once."""

    async def run(raw: dict[str, Any]) -> str | list[Source]:
        try:
            args = DefinitionsInput.model_validate(raw)
        except ValidationError as e:
            return f"Invalid arguments: {e.errors()[0]['msg']}"
        found = glossary()
        concept = found.find(args.term)
        if concept is None:
            return f"No glossary term matches {args.term!r}. Search the corpus for it instead."
        chunk = definitions_chunk(found, concept)
        return [Source(chunk, chunk.title)]

    return Tool(
        name="glossary_definitions",
        description=(
            "What a PLG business term means: every approved version of its glossary definition (current and "
            "superseded) with effective dates, value and source document."
        ),
        input_schema={
            "type": "object",
            "properties": {"term": {"type": "string", "description": "The term, a synonym or a concept ID (plg:Vacant)."}},
            "required": ["term"],
        },
        run=run,
    )
