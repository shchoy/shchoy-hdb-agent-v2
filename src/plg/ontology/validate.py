"""Glossary `supersedes` chain rules, enforced by `make ontology`.

Each concept's versions form one line v1 <- v2 <- ... with no gaps or forks. At most one version is current.
A superseded version ends the day before its successor starts, so every date has one definition in force.
A proposed version supersedes the current one and changes nothing until its owner approves it.
Only a version 1 may omit effective_from, when its start was never recorded.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import timedelta

from plg.ontology.generated.models import GlossaryTerm


def supersedes_errors(terms: Sequence[GlossaryTerm]) -> list[str]:
    errors: list[str] = []
    by_id = {t.id: t for t in terms}
    successors: defaultdict[str, list[GlossaryTerm]] = defaultdict(list)

    for term_id, count in Counter(t.id for t in terms).items():
        if count > 1:
            errors.append(f"{term_id}: duplicate id ({count} terms)")

    for t in terms:
        expected_id = f"{t.concept}_v{t.version}"
        if t.id != expected_id:
            errors.append(f"{t.id}: id should be {expected_id} (concept + version)")
        if t.effective_from is None and t.version > 1:
            errors.append(f"{t.id}: version {t.version} needs effective_from")
        if t.supersedes is None:
            if t.version > 1:
                errors.append(f"{t.id}: version {t.version} must supersede version {t.version - 1}")
            continue
        successors[t.supersedes].append(t)
        previous = by_id.get(t.supersedes)
        if previous is None:
            errors.append(f"{t.id}: supersedes {t.supersedes}, which does not exist")
            continue
        if previous.concept != t.concept:
            errors.append(f"{t.id}: supersedes {previous.id} of another concept ({previous.concept})")
        elif previous.version != t.version - 1:
            errors.append(f"{t.id}: supersedes version {previous.version}, expected {t.version - 1}")
        if t.status == "proposed":
            if previous.status != "current":
                errors.append(f"{t.id}: a proposal must supersede the current version, not {previous.id}")
        elif previous.status != "superseded":
            errors.append(f"{previous.id}: is superseded by {t.id} but its status is {previous.status}")
        elif previous.effective_to is None:
            errors.append(f"{previous.id}: superseded with no effective_to")
        elif t.effective_from and previous.effective_to != (day_before := t.effective_from - timedelta(days=1)):
            errors.append(
                f"{previous.id}: should end on {day_before.isoformat()}, the day before {t.id} starts "
                f"(effective_to is {previous.effective_to.isoformat()})"
            )

    for target, later in successors.items():
        if len(later) > 1:
            errors.append(f"{target}: superseded by both {' and '.join(t.id for t in later)}")

    for t in terms:
        if t.status == "superseded" and not any(s.status != "proposed" for s in successors[t.id]):
            errors.append(f"{t.id}: status superseded but nothing supersedes it")

    current = Counter(t.concept for t in terms if t.status == "current")
    for concept, count in current.items():
        if count > 1:
            errors.append(f"{concept}: {count} current versions")

    return errors
