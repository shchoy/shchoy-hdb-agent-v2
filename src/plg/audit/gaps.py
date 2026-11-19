"""Gaps: questions the corpus answers badly, from the question log and the answer feedback log. A question (grouped by
its normalised wording) is a gap if it got the "not covered" answer, if the best passage any asking retrieved scored
below `min_score`, or if an answer to it got a 👎."""

from __future__ import annotations

import re
from collections.abc import Sequence

from plg.audit.model import Gap, GapReason
from plg.audit.questions import QuestionEntry
from plg.feedback.model import Feedback


def normalise(question: str) -> str:
    return re.sub(r"[\s?.!]+$", "", " ".join(question.casefold().split()))


def find_gaps(entries: Sequence[QuestionEntry], feedback: Sequence[Feedback], min_score: float) -> list[Gap]:
    """Most asked first, then most recently asked."""
    down = {f.run_id for f in feedback if f.score == "down"}
    groups: dict[str, list[QuestionEntry]] = {}
    for entry in entries:
        groups.setdefault(normalise(entry.question), []).append(entry)
    gaps = []
    for asked in groups.values():
        scores = [e.top_score for e in asked if e.top_score is not None]
        top = max(scores) if scores else None
        reasons: list[GapReason] = []
        if any(e.not_covered for e in asked):
            reasons.append("not_covered")
        if top is not None and top < min_score:
            reasons.append("low_score")
        if any(e.run_id in down for e in asked):
            reasons.append("thumbs_down")
        if reasons:
            latest = max(asked, key=lambda e: e.at)
            gaps.append(Gap(question=latest.question, asked=len(asked), last_asked=latest.at, reasons=reasons,
                            top_score=top))
    return sorted(gaps, key=lambda g: (-g.asked, -g.last_asked.timestamp()))
