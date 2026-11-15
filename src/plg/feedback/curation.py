"""What answer feedback teaches the team, held for curators (issue #26).

A 👍 on an answer whose query ran proposes its question → SQL pair; a 👎 with a correction proposes the corrected
answer as an example; a team fact given with any feedback proposes that fact. Each is a `ProposedAction` stored in
the team's memory (`("memory", "team", <kind>)`) with status `pending_review`, invisible to every agent until a
curator approves it (status `active`); a rejection retires it. Curators are team leads, and data analysts for
question → SQL pairs, never the officer whose feedback proposed it; that officer can withdraw it.
"""

from __future__ import annotations

import hashlib
import html
import uuid
from collections.abc import Iterable

from plg.actions.letters import now
from plg.actions.model import (
    APPROVER_ROLES, ActionType, ApprovalDecision, CurationPayload, ExamplePayload, ProposedAction, SqlExamplePayload,
    TeamFactPayload,
)
from plg.feedback.model import AnsweredTurn, Feedback
from plg.identity import UserCtx
from plg.memory.store import ROOT, MemoryStore, mask
from plg.search.models import MemoryItem

TEAM = (ROOT, "team")
KIND: dict[ActionType, str] = {"approve_team_fact": "fact", "approve_example": "example", "approve_sql_example": "sql"}
EDITABLE: dict[ActionType, tuple[str, ...]] = {
    "approve_team_fact": ("fact",),
    "approve_example": ("question", "answer"),
    "approve_sql_example": ("question", "sql"),
}
"""What a curator may change before approving."""
CURATED = tuple(KIND)


def namespace(action_type: ActionType) -> tuple[str, ...]:
    return (*TEAM, KIND[action_type])


def proposals(
    turn: AnsweredTurn, feedback: Feedback, user: UserCtx, staff: Iterable[UserCtx], existing: set[str]
) -> list[ProposedAction]:
    """What this feedback proposes (none for a flagged turn). A question → SQL pair pending or approved (action IDs in
    `existing`) isn't proposed again; a rejected one may be."""
    if turn.flagged:
        return []
    thread_id, run_id, feedback_id = feedback.thread_id, turn.run_id, feedback.feedback_id
    found: list[tuple[ActionType, str, CurationPayload, str]] = []
    if feedback.score == "up" and turn.sql:
        sql_id = "sql-" + hashlib.sha1(f"{_norm(turn.question)}\n{_norm(turn.sql)}".encode()).hexdigest()[:12]
        if not any(e.startswith(sql_id) for e in existing):  # pending or approved already
            sql_id = f"{sql_id}-{uuid.uuid4().hex[:8]}"  # a fresh ID per proposal: the audit log keeps one entry per ID
            payload = SqlExamplePayload(question=mask(turn.question), sql=turn.sql, thread_id=thread_id, run_id=run_id, feedback_id=feedback_id)
            found.append(("approve_sql_example", sql_id, payload, f"SQL example: {_short(turn.question)}"))
    if feedback.score == "down" and feedback.correction.strip():
        payload_e = ExamplePayload(
            question=mask(turn.question), answer=mask(feedback.correction.strip()), original=mask(turn.answer),
            intents=turn.intents, thread_id=thread_id, run_id=run_id, feedback_id=feedback_id,
        )
        found.append(("approve_example", f"ex-{uuid.uuid4()}", payload_e, f"Corrected answer: {_short(turn.question)}"))
    if feedback.team_fact.strip():
        payload_f = TeamFactPayload(fact=mask(feedback.team_fact.strip()), question=mask(turn.question), thread_id=thread_id, run_id=run_id,
            feedback_id=feedback_id,
        )
        found.append(("approve_team_fact", f"fact-{uuid.uuid4()}", payload_f, f"Team fact: {_short(payload_f.fact)}"))
    return [
        ProposedAction(
            action_id=action_id, version=1, action_type=kind, title=title, payload=payload, preview=preview(payload),
            approver_roles=APPROVER_ROLES[kind], proposed_by=user.staff_id, proposed_at=now(),
            approvers=[s.staff_id for s in staff if s.role in APPROVER_ROLES[kind] and s.staff_id != user.staff_id],
        )
        for kind, action_id, payload, title in found
    ]


def edit_errors(action: ProposedAction, edits: dict[str, str]) -> list[str]:
    allowed = EDITABLE[action.action_type]
    errors = [f"{field} can't be edited (only {', '.join(allowed)})" for field in edits if field not in allowed]
    errors += [f"{field} can't be blank" for field, value in edits.items() if field in allowed and not value.strip()]
    return errors


def preview(payload: CurationPayload) -> str:
    e = html.escape
    if isinstance(payload, TeamFactPayload):
        return f"<p><strong>Team fact:</strong> {e(payload.fact)}</p><p>From feedback on: {e(payload.question)}</p>"
    if isinstance(payload, ExamplePayload):
        return (
            f"<p><strong>Question:</strong> {e(payload.question)}</p><p><strong>Corrected answer:</strong> "
            f"{e(payload.answer)}</p><p><strong>Answer given:</strong> {e(payload.original)}</p>"
        )
    return f"<p><strong>Question:</strong> {e(payload.question)}</p><pre>{e(payload.sql)}</pre>"


class Curation:
    """The curated team items in the memory table."""

    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory

    def propose(self, action: ProposedAction) -> None:
        self._write(action)

    def actions(self) -> list[ProposedAction]:
        return [ProposedAction.model_validate(i.value["action"]) for i in self._items()]

    def get(self, action_id: str) -> ProposedAction | None:
        return next((a for a in self.actions() if a.action_id == action_id), None)

    def decide(self, action: ProposedAction, decision: ApprovalDecision) -> ProposedAction:
        """Apply a decision `refusal` found nothing wrong with (and edits `edit_errors` accepted)."""
        if decision.decision == "reject":
            decided = action.model_copy(update={"status": "rejected"})
        else:
            payload = action.payload.model_copy(update={k: mask(v.strip()) if k != "sql" else v.strip() for k, v in decision.edits.items()})
            assert isinstance(payload, TeamFactPayload | ExamplePayload | SqlExamplePayload)
            decided = action.model_copy(update={
                "status": "approved", "payload": payload, "preview": preview(payload),
                "version": action.version + 1 if decision.edits else action.version,
            })
        self._write(decided)
        return decided

    def sql_examples(self, question: str, limit: int = 3) -> list[SqlExamplePayload]:
        """Approved question → SQL pairs nearest the question."""
        return [p for p in self._payloads(self._memory.nearest(namespace("approve_sql_example"), question, limit=limit))
                if isinstance(p, SqlExamplePayload)]

    def corrections(self, question: str, limit: int = 2) -> list[ExamplePayload]:
        """Approved corrected answers nearest the question."""
        return [p for p in self._payloads(self._memory.nearest(namespace("approve_example"), question, limit=limit))
                if isinstance(p, ExamplePayload)]

    def team_facts(self, question: str, limit: int = 5) -> list[str]:
        """Approved team facts nearest the question (a bounded few, however many the team collects)."""
        return [p.fact for p in self._payloads(self._memory.nearest(namespace("approve_team_fact"), question, limit=limit))
                if isinstance(p, TeamFactPayload)]

    def _items(self) -> list[MemoryItem]:
        return [i for i in self._memory.items("team") if "action" in i.value]

    @staticmethod
    def _payloads(items: list[MemoryItem]) -> list[CurationPayload]:
        out: list[CurationPayload] = []
        for i in items:
            payload = _action(i).payload
            assert isinstance(payload, TeamFactPayload | ExamplePayload | SqlExamplePayload)
            out.append(payload)
        return out

    def _write(self, action: ProposedAction) -> None:
        payload = action.payload
        text = (
            payload.fact if isinstance(payload, TeamFactPayload)
            else payload.question if isinstance(payload, ExamplePayload | SqlExamplePayload) else action.title
        )
        status = {"pending": "pending_review", "approved": "active", "rejected": "retired"}[action.status]
        self._memory.put_curated(
            namespace(action.action_type), action.action_id, text, {"text": text, "action": action.model_dump(mode="json")},
            status=status,  # type: ignore[arg-type]
            provenance=f"Feedback from {action.proposed_by}",
        )


def _action(item: MemoryItem) -> ProposedAction:
    return ProposedAction.model_validate(item.value["action"])


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _short(text: str, n: int = 70) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"
