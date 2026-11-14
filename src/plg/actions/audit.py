"""Append-only audit log of decisions on proposed actions: who decided what, when, and in which traced run."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel

from plg.actions.model import ActionType, Decision
from plg.identity import Role


class AuditEntry(BaseModel):
    action_id: str
    version: int
    """The version the approver saw and decided on."""
    action_type: ActionType
    title: str = ""
    """What the action was, e.g. "Send Feedback Update Reply to Sir/Madam"."""
    thread_id: str = ""
    """The conversation the action was proposed in."""
    decision: Decision
    edits: dict[str, str]
    reason: str
    approver: str
    approver_role: Role
    at: str
    run_id: str
    """The LangSmith run ID of the run that carried the decision out."""
    outbox_id: str | None
    """The outbox item sent, or None for a rejection or a ticket."""
    ticket_id: str | None = None
    """The i-EMS ticket raised, or None for a rejection or a letter."""
    term_id: str | None = None
    """The glossary term version adopted (e.g. plg:Vacant_v3), or None for a rejection or another action."""


class AuditLog:
    """JSON lines, only ever appended to. One entry per decided action: recording it again is a no-op."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        with self._lock:
            if any(e.action_id == entry.action_id for e in self.entries()):
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log:
                log.write(entry.model_dump_json() + "\n")

    def entries(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [AuditEntry.model_validate_json(line) for line in lines if line.strip()]

    def decided_by(self, staff_id: str) -> list[AuditEntry]:
        """One officer's decisions, newest first."""
        return [e for e in reversed(self.entries()) if e.approver == staff_id]
