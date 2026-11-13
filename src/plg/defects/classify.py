"""Feedback classification: Haiku names every category the feedback could belong to, with its confidence; the rules
here choose one. Several plausible categories make the classification low confidence and resolve to the most
severe of them, so a safety issue (a wet ceiling with flickering lights: electrical) is never under-classified."""

from __future__ import annotations

from pydantic import BaseModel

from plg.agents.runtime import CACHE
from plg.defects.taxonomy import SEVERITY_RANK, SLA_DAYS, Severity, Taxonomy
from plg.llm import Block, LLMClient

NODE = "defect"
TOOL = "classify_feedback"

CANDIDATE_MIN = 0.3
"""A category named with at least this confidence is a plausible reading of the feedback."""
LOW_CONFIDENCE = 0.6
"""Below this, the classification is flagged for the officer to check."""
AMBIGUOUS_CAP = 0.5
"""The confidence reported when several categories are plausible: the choice is a rule, not a reading."""

SYSTEM = """\
You classify public and tenant feedback received by the Properties & Land Group (PLG) into its feedback taxonomy, \
so it can be routed. The categories:
{categories}

Name every category the feedback could belong to, each with your confidence (0 to 1) that it does; name more than \
one when the feedback describes several problems or is unclear. Complaints about tenants' behaviour, the common \
area or general enquiries are not maintenance defects: use their own category. Give a one- or two-sentence \
rationale quoting the words that decided it."""


class Candidate(BaseModel):
    code: str
    category: str
    severity: Severity
    confidence: float


class Classification(BaseModel):
    category_code: str
    category: str
    severity: Severity
    team: str
    vendor: str | None
    """The term contractor for the category; None when the team handles it itself."""
    is_defect: bool
    """A maintenance defect, raised as an i-EMS ticket; otherwise handled without one."""
    sla_days: int | None
    """i-EMS completion SLA for the severity; None for non-defects."""
    confidence: float
    low_confidence: bool
    """Several categories were plausible, or the one chosen was uncertain: an officer should check it."""
    rationale: str
    candidates: list[Candidate]
    """Every plausible category, most likely first."""


def tool(taxonomy: Taxonomy) -> Block:
    return {
        "name": TOOL,
        "description": "Record the categories the feedback belongs to.",
        "input_schema": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "enum": taxonomy.codes},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["code", "confidence"],
                    },
                },
                "rationale": {"type": "string"},
                "feedback": {
                    "type": "string",
                    "description": "The feedback itself, word for word as the officer gave it, without their request to you.",
                },
            },
            "required": ["categories", "rationale", "feedback"],
        },
        "cache_control": CACHE,
    }


async def classify(llm: LLMClient, taxonomy: Taxonomy, question: str, context: str = "") -> tuple[Classification, str]:
    """Classify the feedback in `question`; `context` adds what PLG Records hold about a feedback case it names.
    Also returns the feedback itself, without the officer's request (the ticket's description)."""
    system: list[Block] = [{"type": "text", "text": SYSTEM.format(categories=taxonomy.describe()), "cache_control": CACHE}]
    if context:
        system.append({"type": "text", "text": context})
    reply = await llm.complete(
        node=NODE, tier="haiku", system=system, messages=[{"role": "user", "content": question}],
        tools=[tool(taxonomy)], tool_choice={"type": "tool", "name": TOOL},
    )
    call = next(b for b in reply.content if b["type"] == "tool_use")
    named = {str(c["code"]): float(c["confidence"]) for c in call["input"].get("categories", [])}
    found = resolve(taxonomy, named, str(call["input"].get("rationale", "")))
    return found, str(call["input"].get("feedback", "")).strip() or question


def resolve(taxonomy: Taxonomy, named: dict[str, float], rationale: str) -> Classification:
    """Choose among the named categories: the most severe plausible one (then the most likely)."""
    scored = sorted(
        (Candidate(code=c.code, category=c.label, severity=c.default_severity, confidence=conf)
         for code, conf in named.items() if (c := taxonomy.get(code))),
        key=lambda c: -c.confidence,
    )
    if not scored:
        scored = [Candidate(code="OTH", category=taxonomy.categories["OTH"].label, severity="Low", confidence=0.0)]
    plausible = [c for c in scored if c.confidence >= CANDIDATE_MIN] or scored[:1]
    chosen = max(plausible, key=lambda c: (SEVERITY_RANK[c.severity], c.confidence))
    category = taxonomy.categories[chosen.code]
    ambiguous = len(plausible) > 1
    confidence = min(chosen.confidence, AMBIGUOUS_CAP) if ambiguous else chosen.confidence
    return Classification(
        category_code=category.code, category=category.label, severity=category.default_severity,
        team=category.team, vendor=category.vendor if category.iems else None, is_defect=category.iems,
        sla_days=SLA_DAYS[category.default_severity] if category.iems else None,
        confidence=confidence, low_confidence=ambiguous or confidence < LOW_CONFIDENCE,
        rationale=rationale, candidates=plausible,
    )
