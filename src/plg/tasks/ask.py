"""The `tasks` specialist's reading of a question: whose tasks (the officer's own unless a colleague is named) and how
many (`top N`, default 5). Deterministic: no Claude."""

from __future__ import annotations

import re

from plg.identity import UserCtx
from plg.tasks.rules import DEFAULT_LIMIT, clamp

NODE = "tasks"
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

NOT_ALLOWED = (
    "{viewer} ({title}) is not allowed to view {target}'s tasks: officers see only their own tasks, team leads "
    "those of their department's officers, directors everyone's. No tasks were read."
)
RATIONALE = (
    "Give the officer one short sentence per task on why it sits where it does, from its urgency, impact and reasons; "
    "say plainly which tasks are overdue."
)
NO_USER = "No officer is signed in, so there are no tasks to rank."


def whose(question: str, user: UserCtx, staff: list[UserCtx]) -> UserCtx:
    """The colleague the question names (full name, staff ID, or a first name only one colleague has, used possessively:
    "Daniel's tasks"), else the asker."""
    text = question.lower().replace("\u2019", "'")
    for person in staff:
        if person.name.lower() in text or re.search(rf"\b{person.staff_id.lower()}\b", text):
            return person
    first = [p for p in staff if re.search(rf"\b{re.escape(p.name.split()[0].lower())}'s\b", text)]
    return first[0] if len(first) == 1 else user


def how_many(question: str) -> int:
    found = re.search(rf"\btop\s+(\d+|{'|'.join(NUMBERS)})\b", question.lower())
    if not found:
        return DEFAULT_LIMIT
    n = NUMBERS.get(found.group(1)) or int(found.group(1))
    return clamp(n)
