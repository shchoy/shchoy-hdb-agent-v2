"""The task rules matrix: an officer's open tasks (PLG Records `tasks`) ranked by urgency × impact. Deterministic, no
Claude: the reasons for each task's place come from the rules; Claude only words the rationale (merge).

Urgency (from the due date, on the records' `today`): overdue 4, due this week (within 7 days) 3, due within 30 days 2,
later 1. Impact: high 3 (safety-related, S$50,000+ rent at risk or 5+ tenants affected), medium 2 (S$10,000+ at risk
or 2+ tenants), low 1. Score = urgency × impact; ties go to the earlier due date, then the larger rent at risk.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from plg.identity import UserCtx

Urgency = Literal["overdue", "this_week", "soon", "later"]
Impact = Literal["high", "medium", "low"]

URGENCY_SCORE: dict[Urgency, int] = {"overdue": 4, "this_week": 3, "soon": 2, "later": 1}
IMPACT_SCORE: dict[Impact, int] = {"high": 3, "medium": 2, "low": 1}
THIS_WEEK_DAYS = 7
SOON_DAYS = 30
HIGH_REVENUE = 50_000.0
MEDIUM_REVENUE = 10_000.0
HIGH_TENANTS = 5
MEDIUM_TENANTS = 2
DEFAULT_LIMIT = 5
MAX_LIMIT = 50

LEADS = ("director", "manager", "estate_manager")
"""Roles that lead a team; a lead sees the tasks of the officers in their department (directors: everyone's)."""


class Task(BaseModel):
    """One row of PLG Records `tasks`."""

    task_id: str
    task_type: str
    title: str
    related_id: str
    due_date: dt.date
    status: str
    safety_flag: bool
    revenue_at_risk: float
    tenants_affected: int


class RankedTask(Task):
    rank: int
    urgency: Urgency
    impact: Impact
    score: int
    """Urgency × impact (1-12)."""
    overdue: bool
    days_overdue: int
    """0 unless overdue."""
    reasons: list[str]
    """Why the task sits where it does, from the rules: due date, safety, rent at risk, tenants affected."""


class TaskDigest(BaseModel):
    """An officer's top open tasks on `as_of`, ranked by urgency × impact."""

    staff_id: str
    name: str
    title: str
    as_of: dt.date
    open_count: int
    overdue_count: int
    tasks: list[RankedTask]


def can_view(viewer: UserCtx, target: UserCtx) -> bool:
    """Everyone sees their own tasks; directors see everyone's; other leads see their department's officers'."""
    if viewer.staff_id == target.staff_id or viewer.role == "director":
        return True
    return viewer.role in LEADS and target.dept == viewer.dept and target.role not in LEADS


def team(viewer: UserCtx, staff: list[UserCtx]) -> list[UserCtx]:
    """The staff whose tasks `viewer` may view, themselves first."""
    others = [s for s in staff if s.staff_id != viewer.staff_id and can_view(viewer, s)]
    return [viewer, *others]


def urgency(task: Task, today: dt.date) -> Urgency:
    days = (task.due_date - today).days
    if days < 0 or task.status == "Overdue":
        return "overdue"
    if days < THIS_WEEK_DAYS:
        return "this_week"
    return "soon" if days <= SOON_DAYS else "later"


def impact(task: Task) -> Impact:
    if task.safety_flag or task.revenue_at_risk >= HIGH_REVENUE or task.tenants_affected >= HIGH_TENANTS:
        return "high"
    if task.revenue_at_risk >= MEDIUM_REVENUE or task.tenants_affected >= MEDIUM_TENANTS:
        return "medium"
    return "low"


def reasons(task: Task, today: dt.date) -> list[str]:
    days = (task.due_date - today).days
    due = _day(task.due_date)
    if days < 0:
        found = [f"Overdue by {-days} day{'s' if days != -1 else ''} (due {due})"]
    elif task.status == "Overdue":
        found = [f"Marked overdue (due {due})"]
    elif days == 0:
        found = ["Due today"]
    else:
        found = [f"Due in {days} day{'s' if days != 1 else ''} ({due})"]
    if task.safety_flag:
        found.append("Safety-related")
    if task.revenue_at_risk > 0:
        found.append(f"S${task.revenue_at_risk:,.0f} rent at risk")
    if task.tenants_affected > 1:
        found.append(f"{task.tenants_affected} tenants affected")
    return found


def clamp(limit: int) -> int:
    """How many tasks to show: at least one, at most MAX_LIMIT."""
    return max(1, min(limit, MAX_LIMIT))


def rank(tasks: list[Task], today: dt.date, limit: int) -> list[RankedTask]:
    """The open tasks (not Done) in rank order, top `limit` (at most MAX_LIMIT)."""
    scored = []
    for task in tasks:
        if task.status == "Done":
            continue
        u, i = urgency(task, today), impact(task)
        scored.append((URGENCY_SCORE[u] * IMPACT_SCORE[i], u, i, task))
    scored.sort(key=lambda s: (-s[0], -URGENCY_SCORE[s[1]], s[3].due_date, -s[3].revenue_at_risk, s[3].task_id))
    return [
        RankedTask(
            **task.model_dump(), rank=n, urgency=u, impact=i, score=score, overdue=u == "overdue",
            days_overdue=max(0, (today - task.due_date).days), reasons=reasons(task, today),
        )
        for n, (score, u, i, task) in enumerate(scored[: clamp(limit)], start=1)
    ]


def load_tasks(records_db: Path, staff_id: str) -> list[Task]:
    """The officer's tasks that are not done, read-only."""
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT task_id, task_type, title, related_id, due_date, status, safety_flag, revenue_at_risk, "
            "tenants_affected FROM tasks WHERE assignee_id = ? AND status != 'Done'",
            (staff_id,),
        ).fetchall()
    fields = list(Task.model_fields)
    return [Task.model_validate(dict(zip(fields, row))) for row in rows]


def digest(records_db: Path, officer: UserCtx, today: dt.date, limit: int = DEFAULT_LIMIT) -> TaskDigest:
    tasks = load_tasks(records_db, officer.staff_id)
    return TaskDigest(
        staff_id=officer.staff_id, name=officer.name, title=officer.title, as_of=today,
        open_count=len(tasks), overdue_count=sum(urgency(t, today) == "overdue" for t in tasks),
        tasks=rank(tasks, today, limit),
    )


def render(digest: TaskDigest) -> str:
    """The digest as plain text (console, file, and the finding merge words the rationale from)."""
    lines = [
        f"Top {len(digest.tasks)} of {digest.name}'s ({digest.staff_id}, {digest.title}) {digest.open_count} open tasks "
        f"as of {_day(digest.as_of)}, ranked by urgency × impact ({digest.overdue_count} overdue):",
    ]
    for t in digest.tasks:
        mark = "OVERDUE " if t.overdue else ""
        lines.append(
            f"{t.rank}. {mark}{t.task_id} {t.task_type}: {t.title} ({t.related_id}), status {t.status}. "
            f"Urgency {t.urgency.replace('_', ' ')} ({URGENCY_SCORE[t.urgency]}) × impact {t.impact} "
            f"({IMPACT_SCORE[t.impact]}) = {t.score}. {'; '.join(t.reasons)}."
        )
    if not digest.tasks:
        lines.append("No open tasks.")
    return "\n".join(lines)


def _day(d: dt.date) -> str:
    return f"{d.day} {d:%b %Y}"
