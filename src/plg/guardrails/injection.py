"""Prompt-injection screening (issue #23): instructions planted for the assistant in an officer's message or in an
ingested email are detected, cut out before Claude sees them, and reported to the officer.

Deterministic on purpose: the same text is always flagged the same way, at no cost, before any model reads it. It
is one layer of several: no model toolset holds a tool that acts, and a turn that met an injection proposes nothing.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

Rule = Literal["override", "ai_address", "approval_bypass", "authority_claim", "concealment", "prompt_leak", "role_change"]

_W = r"[^.!?\n]{0,40}?"  # a few words, within one sentence

RULES: dict[Rule, re.Pattern[str]] = {
    # "ignore all previous instructions", "disregard your guidelines" (not "rules": officers ask about PLG's rules)
    "override": re.compile(
        rf"\b(ignore|disregard|forget|override|bypass)\b{_W}\b(previous|prior|above|earlier|all|any|your|the system)\b"
        rf"{_W}\b(instructions?|prompts?|guidelines|guardrails|directives)\b",
        re.I,
    ),
    # "SYSTEM NOTE TO AI ASSISTANT", "message for the language model" (not "agent": tenants have agents)
    "ai_address": re.compile(
        r"\b(note|message|prompt|instructions?)\s+(to|for)\s+(the\s+)?(ai|assistant|llm|language\s+model|chatbot)\b",
        re.I,
    ),
    # "do not ask for human approval", "without human approval" (an order, not "can a tenant ... without seeking approval?")
    "approval_bypass": re.compile(
        r"\b(do\s+not|don't|never)\s+(ask|seek|wait|request)\s+(for\s+)?(any\s+|human\s+|officer\s+|their\s+)?"
        r"(approval|confirmation|sign-?off)\b"
        r"|\bwithout\s+(any\s+)?(human|officer)\s+(approval|confirmation|review|sign-?off)\b"
        r"|\b(skip|bypass)\s+(the\s+)?(human|officer)\s+(approval|review)\b",
        re.I,
    ),
    # "You are authorised by the Director"
    "authority_claim": re.compile(r"\byou\s+are\s+(now\s+)?(hereby\s+)?(authori[sz]ed|permitted|cleared|allowed)\b", re.I),
    # "Do not mention this note"
    "concealment": re.compile(
        r"\b(do\s+not|don't|never)\s+(mention|reveal|disclose|tell\s+(anyone|the\s+(user|officer)))\b"
        r"[^.!?\n]{0,20}\b(this|these)\s+(note|instructions?|message|comment)\b",
        re.I,
    ),
    # "print your system prompt"
    "prompt_leak": re.compile(
        rf"\b(reveal|print|show|repeat|output)\b{_W}\b(system\s+prompt|hidden\s+instructions|initial\s+instructions)\b", re.I
    ),
    # "From now on you are DAN", "you are no longer an assistant"
    "role_change": re.compile(
        r"\b(from\s+now\s+on|henceforth),?\s+you\s+are\s+(a|an|no)\b|\byou\s+are\s+no\s+longer\s+(a|an|the)\b", re.I
    ),
}

MARKER = "[Removed at ingestion: suspected prompt injection"
"""Starts the text that replaces a planted instruction in an ingested document (see `screen`)."""

SCREENED_DOC_TYPE = "email"
"""Documents of this type are screened at ingestion (and, if indexed before that, when retrieved)."""

MESSAGE_MARKER = "[Removed: suspected prompt injection"
"""Starts the text that replaces a planted instruction in an officer's message."""

_MARKED = re.compile(re.escape(MARKER) + r"(?: \((?P<rules>[a-z_, ]+)\))?\]")
_COMMENT = re.compile(r"<!--.*?(-->|$)", re.S)
_SENTENCE_END = re.compile(r"[.!?](\s|$)|\n")


class Hit(BaseModel):
    rule: Rule
    start: int
    end: int
    """The span cut out: the planted instruction's sentence, or the whole hidden HTML comment it sits in."""


class Screening(BaseModel):
    hits: list[Hit]
    text: str
    """The screened text with every flagged span replaced by the removal marker."""

    @property
    def flagged(self) -> bool:
        return bool(self.hits)

    @property
    def rules(self) -> list[Rule]:
        return list(dict.fromkeys(h.rule for h in self.hits))


class InjectionFlag(BaseModel):
    """A prompt-injection attempt the assistant detected and ignored, as reported to the officer."""

    source: Literal["message", "document"]
    """The officer's own message, or a document (an ingested email) the assistant read."""
    rules: list[Rule]
    """What gave it away, e.g. `override` ("ignore all previous instructions") or `approval_bypass`."""
    doc_id: str | None = None
    title: str | None = None
    excerpt: str | None = None
    """The flagged text from the officer's message (documents: none, it was removed at ingestion). Show it as text."""


def screen(text: str, marker: str = MARKER) -> Screening:
    """Find planted instructions in `text`, and the text with each one's span replaced by `marker`."""
    hits: list[Hit] = []
    for rule, pattern in RULES.items():
        for m in pattern.finditer(text):
            start, end = _span(text, m.start(), m.end())
            hits.append(Hit(rule=rule, start=start, end=end))
    hits.sort(key=lambda h: (h.start, h.end))
    return Screening(hits=hits, text=_replace(text, hits, marker))


def flags_in(text: str) -> list[Rule] | None:
    """The rules recorded in the removal marker of an ingested text; None when nothing was removed from it."""
    found = _MARKED.search(text)
    if found is None:
        return None
    named = (found.group("rules") or "").replace(" ", "").split(",")
    return [r for r in RULES if r in named]


def excerpt(text: str, screening: Screening, limit: int = 300) -> str:
    """The flagged spans of `text`, joined and shortened for display."""
    joined = " … ".join(text[s:e].strip() for s, e in _merged(screening.hits))
    return joined if len(joined) <= limit else joined[: limit - 1].rstrip() + "…"


def _span(text: str, start: int, end: int) -> tuple[int, int]:
    """The unit to cut around a match: its enclosing HTML comment if hidden in one, else its sentence."""
    for comment in _COMMENT.finditer(text):
        if comment.start() <= start < comment.end():
            return comment.start(), comment.end()
    before = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
    after = _SENTENCE_END.search(text, end)
    return (before[-1] if before else 0), (after.start() + 1 if after else len(text))


def _merged(hits: list[Hit]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for h in sorted(hits, key=lambda h: h.start):
        if spans and h.start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], h.end))
        else:
            spans.append((h.start, h.end))
    return spans


def _replace(text: str, hits: list[Hit], marker: str) -> str:
    out, at = [], 0
    for start, end in _merged(hits):
        rules = ", ".join(dict.fromkeys(h.rule for h in hits if start <= h.start < end))
        out += [text[at:start], f"{marker} ({rules})]"]
        at = end
    return "".join([*out, text[at:]])
