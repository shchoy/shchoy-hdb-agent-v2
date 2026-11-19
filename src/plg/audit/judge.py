"""Opus judges the audit's candidates (one call each, its tool required by the prompt, the system prompt and tool cached).

Nothing it says is trusted: a conflict side or a superseded-definition finding must name a chunk it was shown and
quote it verbatim (whitespace aside), else it is dropped and the reason kept. What Opus wrote in its own words
(topics, resolutions, notes, explanations) is PII-masked by the caller's `mask`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from plg.agents.runtime import CACHE
from plg.audit.candidates import DefinitionCandidate, DuplicateCandidate, PairCandidate, RecordPassage
from plg.audit.model import (
    Conflict, DocRef, Duplicate, DuplicateKind, Side, SupersededDefinition,
)
from plg.llm import AgentMessage, AgentTurn, Block, LLMClient
from plg.ontology.glossary import Glossary
from plg.search.models import Chunk, DocumentMeta

NODE = "audit"
PAIR_TOOL = "record_judgement"
DEFINITION_TOOL = "record_definition_use"
MAX_CHUNKS = 8
"""Chunks of each document shown when judging a duplicate."""

PAIR_SYSTEM = """\
You audit the document library of PLG (the Properties & Land Group, which lets commercial units in public housing \
estates) for a policy owner. You are shown passages from two sources: two documents, or a document and a row of \
PLG Records (the tenancy database). Record your judgement with the record_judgement tool.

- relation "duplicate": the two documents are copies of each other or versions of one document. Give the kind: \
"same_content" (the same text in another file or format), "near_duplicate" (the same document with small edits, \
e.g. a renamed copy), or "earlier_version" (an earlier and a later version of one controlled document). Say in \
`note` what differs, in one sentence.
- relation "conflict": they state different things on the same point (an amount, a period, a limit, a rule), so \
an officer reading one would act differently from one reading the other. Record each conflict: its topic, the chunk \
and a verbatim quote (copied character for character, as short as makes the point) from each side, the expected \
resolution in one or two sentences, and which side prevails ("a", "b", or "none" if neither clearly does). A current \
policy prevails over SOPs, guides, FAQs and emails that contradict it; a circular overrides the clause it names, for \
the scope it states; a signed agreement prevails over a data entry. Sources that agree, or that differ only because \
they are about different things, do not conflict.
- relation "none": neither.
Use only what the passages say."""

DEFINITION_SYSTEM = """\
You audit reports and decks of PLG (the Properties & Land Group) for figures that count by a business definition \
that is no longer in force. You are shown passages of one document and the glossary's versions of the business \
terms they mention (each with its dates in force). For each figure that counts by a superseded version where the \
current version applies (e.g. a count that includes what the current definition excludes), record the concept, the \
superseded version's ID, the chunk and a verbatim quote of the figure (copied character for character), and a one \
or two sentence explanation (what the figure would be or how it differs under the current definition, if the \
passages say). Record nothing for figures that follow the current definition or that the passages give no reason \
to doubt. Use the record_definition_use tool."""


def pair_request(candidate: PairCandidate) -> str:
    """The opening text block of a conflict judgement's user message: stable, naming the two sources."""
    return f"Do these sources conflict: {candidate.a.doc_id} and {candidate.b_id}?"


def duplicate_request(candidate: DuplicateCandidate) -> str:
    return f"Are these documents duplicates: {candidate.a.doc_id} and {candidate.b.doc_id}?"


def definition_request(candidate: DefinitionCandidate) -> str:
    return f"Which figures in {candidate.doc.doc_id} use a superseded definition?"


def pair_tool() -> Block:
    return {
        "name": PAIR_TOOL,
        "description": "Record whether the two sources are duplicates, conflict, or neither.",
        "input_schema": {
            "type": "object",
            "properties": {
                "relation": {"enum": ["duplicate", "conflict", "none"]},
                "duplicate_kind": {"enum": ["same_content", "near_duplicate", "earlier_version"]},
                "note": {"type": "string"},
                "conflicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"},
                            "a_chunk_id": {"type": "string"},
                            "a_quote": {"type": "string"},
                            "b_chunk_id": {"type": "string"},
                            "b_quote": {"type": "string"},
                            "resolution": {"type": "string"},
                            "prevails": {"enum": ["a", "b", "none"]},
                        },
                        "required": ["topic", "a_chunk_id", "a_quote", "b_chunk_id", "b_quote", "resolution", "prevails"],
                    },
                },
            },
            "required": ["relation"],
        },
        "cache_control": CACHE,
    }


def definition_tool() -> Block:
    return {
        "name": DEFINITION_TOOL,
        "description": "Record the figures that use a superseded definition (none if there are none).",
        "input_schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {"type": "string"},
                            "used_version": {"type": "string", "description": "The superseded version's ID."},
                            "chunk_id": {"type": "string"},
                            "quote": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["concept", "used_version", "chunk_id", "quote", "explanation"],
                    },
                },
            },
            "required": ["findings"],
        },
        "cache_control": CACHE,
    }


# ---------------------------------------------------------------- listings


def _describe(doc: DocumentMeta) -> str:
    parts = [doc.doc_type, doc.status]
    if doc.version:
        parts.append(f"version {doc.version}")
    if doc.effective_from:
        parts.append(f"effective {doc.effective_from.isoformat()}")
    if doc.effective_to:
        parts.append(f"to {doc.effective_to.isoformat()}")
    return f"{doc.title} ({', '.join(parts)})"


def _chunks(chunks: Sequence[Chunk]) -> str:
    return "\n".join(f'<chunk id="{c.chunk_id}" location="{c.location}">\n{c.text}\n</chunk>' for c in chunks)


def pair_listing(candidate: PairCandidate) -> str:
    b = candidate.b
    if isinstance(b, RecordPassage):
        b_part = f'<source side="b" id="{b.chunk_id}">\n{b.title}\n<chunk id="{b.chunk_id}" location="PLG Records">\n{b.text}\n</chunk>\n</source>'
    else:
        b_part = f'<source side="b" id="{b.doc_id}">\n{_describe(b)}\n{_chunks(candidate.b_chunks)}\n</source>'
    a_part = f'<source side="a" id="{candidate.a.doc_id}">\n{_describe(candidate.a)}\n{_chunks(candidate.a_chunks)}\n</source>'
    return f"{a_part}\n\n{b_part}"


def duplicate_listing(candidate: DuplicateCandidate, a_chunks: Sequence[Chunk], b_chunks: Sequence[Chunk]) -> str:
    return (
        f'<source side="a" id="{candidate.a.doc_id}">\n{_describe(candidate.a)}\n{_chunks(a_chunks[:MAX_CHUNKS])}\n</source>\n\n'
        f'<source side="b" id="{candidate.b.doc_id}">\n{_describe(candidate.b)}\n{_chunks(b_chunks[:MAX_CHUNKS])}\n</source>'
    )


def definition_listing(candidate: DefinitionCandidate, glossary: Glossary) -> str:
    terms = []
    for concept in candidate.concepts:
        for v in glossary.versions(concept):
            period = f"{v.effective_from or 'before records'} to {v.effective_to or 'now'}"
            terms.append(f"- {v.id} ({v.status}, in force {period}): {v.pref_label}: {v.definition.strip()}"
                         + (f" [{v.value}]" if v.value else ""))
    return (
        f'<document id="{candidate.doc.doc_id}">\n{_describe(candidate.doc)}\n{_chunks(candidate.chunks)}\n</document>\n\n'
        "Glossary versions:\n" + "\n".join(terms)
    )


# ---------------------------------------------------------------- validation


def squash(text: str) -> str:
    return " ".join(text.split())


def verbatim(quote: str, text: str) -> bool:
    q = squash(quote)
    return bool(q) and q in squash(text)


def _call(reply: AgentTurn, name: str) -> dict[str, Any] | None:
    call = next((b for b in reply.content if b["type"] == "tool_use" and b.get("name") == name), None)
    return call["input"] if call and isinstance(call.get("input"), dict) else None


class _Clash(BaseModel):
    topic: str
    a_chunk_id: str
    a_quote: str
    b_chunk_id: str
    b_quote: str
    resolution: str
    prevails: Literal["a", "b", "none"] = "none"


class _Judgement(BaseModel):
    relation: Literal["duplicate", "conflict", "none"]
    duplicate_kind: DuplicateKind | None = None
    note: str = ""
    conflicts: list[_Clash] = []


def conflict_id(a: str, b: str, a_chunk: str, b_chunk: str) -> str:
    return "CF-" + hashlib.sha1("|".join([a, b, a_chunk, b_chunk]).encode()).hexdigest()[:10]


@dataclass
class PairVerdict:
    conflicts: list[Conflict] = field(default_factory=list)
    duplicate: Duplicate | None = None
    dropped: list[str] = field(default_factory=list)


TOOL_ONLY = "Answer only by calling the {tool} tool, never in plain text."
"""Opus rejects a forced tool_choice ("tool"/"any"), so the tool is offered with "auto" and the prompt insists on it."""


async def _ask(llm: LLMClient, system: str, tool: Block, request: str, listing: str) -> AgentTurn:
    """One Opus judgement: the opening request text (what scripted tests key on), then the listing. A reply that
    doesn't call the tool is asked once more; if it still doesn't, the caller records the item as dropped."""
    name = str(tool["name"])
    messages: list[AgentMessage] = [{"role": "user", "content": [
        {"type": "text", "text": request}, {"type": "text", "text": listing},
    ]}]
    prompt = [{"type": "text", "text": f"{system}\n\n{TOOL_ONLY.format(tool=name)}", "cache_control": CACHE}]
    reply = await llm.complete(
        node=NODE, tier="opus", system=prompt, messages=messages, tools=[tool], tool_choice={"type": "auto"},
    )
    if _call(reply, name) is not None or reply.stop_reason == "tool_use":
        return reply
    messages += [
        {"role": "assistant", "content": reply.content},
        {"role": "user", "content": [
            {"type": "text", "text": request}, {"type": "text", "text": f"Record your judgement now with the {name} tool."},
        ]},
    ]
    return await llm.complete(
        node=NODE, tier="opus", system=prompt, messages=messages, tools=[tool], tool_choice={"type": "auto"},
    )


def _side(chunk: Chunk, quote: str) -> Side:
    return Side(doc_id=chunk.doc_id, title=chunk.title, chunk_id=chunk.chunk_id, location=chunk.location,
                version=chunk.version, quote=quote)


async def judge_pair(llm: LLMClient, candidate: PairCandidate, mask: Callable[[str], str]) -> PairVerdict:
    """Opus on whether two sources conflict; each conflict it records is kept only if both quotes are verbatim spans of
    chunks it was shown on that side."""
    reply = await _ask(llm, PAIR_SYSTEM, pair_tool(), pair_request(candidate), pair_listing(candidate))
    verdict = PairVerdict()
    label = f"{candidate.a.title} / {candidate.b.title}"
    judgement = _parse(reply, label, verdict.dropped)
    if judgement is None or judgement.relation != "conflict":
        return verdict
    a_chunks = {c.chunk_id: c for c in candidate.a_chunks}
    b_chunks = {c.chunk_id: c for c in candidate.b_chunks}
    for clash in judgement.conflicts:
        a = a_chunks.get(clash.a_chunk_id)
        if a is None or not verbatim(clash.a_quote, a.text):
            verdict.dropped.append(f"{label}: {clash.topic}: side a's quote is not a verbatim span of a chunk shown")
            continue
        b_side: Side | None
        if isinstance(candidate.b, RecordPassage):
            record = candidate.b
            ok = clash.b_chunk_id == record.chunk_id and verbatim(clash.b_quote, record.text)
            b_side = Side(doc_id=None, title=record.title, chunk_id=record.chunk_id, location="PLG Records",
                          quote=clash.b_quote) if ok else None
        else:
            b = b_chunks.get(clash.b_chunk_id)
            b_side = _side(b, clash.b_quote) if b is not None and verbatim(clash.b_quote, b.text) else None
        if b_side is None:
            verdict.dropped.append(f"{label}: {clash.topic}: side b's quote is not a verbatim span of a chunk shown")
            continue
        verdict.conflicts.append(Conflict(
            id=conflict_id(candidate.a.doc_id, candidate.b_id, a.chunk_id, b_side.chunk_id or ""),
            topic=mask(clash.topic), a=_side(a, clash.a_quote), b=b_side, resolution=mask(clash.resolution),
            prevails=None if clash.prevails == "none" else clash.prevails, found_by=list(candidate.found_by),
        ))
    return verdict


async def judge_duplicate(
    llm: LLMClient, candidate: DuplicateCandidate, a_chunks: Sequence[Chunk], b_chunks: Sequence[Chunk],
    mask: Callable[[str], str],
) -> PairVerdict:
    """Opus confirms (or not) that a MinHash candidate is a duplicate, and of which kind."""
    reply = await _ask(
        llm, PAIR_SYSTEM, pair_tool(), duplicate_request(candidate), duplicate_listing(candidate, a_chunks, b_chunks)
    )
    verdict = PairVerdict()
    judgement = _parse(reply, f"{candidate.a.title} / {candidate.b.title}", verdict.dropped)
    if judgement is not None and judgement.relation == "duplicate":
        verdict.duplicate = Duplicate(
            a=DocRef.of(candidate.a), b=DocRef.of(candidate.b), similarity=candidate.similarity,
            kind=judgement.duplicate_kind or "near_duplicate", note=mask(judgement.note.strip()),
        )
    return verdict


def _parse(reply: AgentTurn, label: str, dropped: list[str]) -> _Judgement | None:
    raw = _call(reply, PAIR_TOOL)
    if raw is None:
        dropped.append(f"{label}: no judgement recorded")
        return None
    try:
        return _Judgement.model_validate(raw)
    except ValidationError as exc:
        dropped.append(f"{label}: unreadable judgement ({exc.errors()[0]['msg']})")
        return None


class _Use(BaseModel):
    concept: str
    used_version: str
    chunk_id: str
    quote: str
    explanation: str


@dataclass
class DefinitionVerdict:
    findings: list[SupersededDefinition] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


async def judge_definition(
    llm: LLMClient, candidate: DefinitionCandidate, glossary: Glossary, mask: Callable[[str], str]
) -> DefinitionVerdict:
    """Opus on which figures of one report use a superseded definition; a finding must name a superseded version of a
    concept it was shown and quote a chunk it was shown verbatim."""
    reply = await _ask(
        llm, DEFINITION_SYSTEM, definition_tool(), definition_request(candidate), definition_listing(candidate, glossary)
    )
    verdict = DefinitionVerdict()
    raw = _call(reply, DEFINITION_TOOL)
    if raw is None:
        verdict.dropped.append(f"{candidate.doc.title}: no judgement recorded")
        return verdict
    chunks = {c.chunk_id: c for c in candidate.chunks}
    for item in raw.get("findings", []) if isinstance(raw.get("findings"), list) else []:
        try:
            use = _Use.model_validate(item)
        except ValidationError:
            verdict.dropped.append(f"{candidate.doc.title}: unreadable finding")
            continue
        concept = use.concept if use.concept in candidate.concepts else glossary.find(use.concept)
        used = next((v for v in glossary.versions(concept or "") if v.id == use.used_version), None)
        current = glossary.current(concept or "")
        chunk = chunks.get(use.chunk_id)
        label = f"{candidate.doc.title}: {use.used_version}"
        if concept not in candidate.concepts or used is None or current is None or used.status != "superseded":
            verdict.dropped.append(f"{label}: not a superseded version of a term shown")
        elif chunk is None or not verbatim(use.quote, chunk.text):
            verdict.dropped.append(f"{label}: the quote is not a verbatim span of a chunk shown")
        else:
            verdict.findings.append(SupersededDefinition(
                doc=DocRef.of(candidate.doc), chunk_id=chunk.chunk_id, location=chunk.location, quote=use.quote,
                concept=current.concept, used_version=used.id, current_version=current.id,
                current_from=current.effective_from, explanation=mask(use.explanation),
            ))
    return verdict
