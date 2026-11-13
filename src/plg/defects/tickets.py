"""The `TicketSystem` adapter: i-EMS, where approved defect tickets are raised. The POC writes them to local storage."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from plg.defects.taxonomy import Severity


class Ticket(BaseModel):
    ticket_id: str
    action_id: str
    version: int
    """The version raised: one above the approved version when the officer edited it."""
    feedback_id: str
    """The feedback case the ticket was raised from."""
    description: str
    unit_id: str | None
    category_code: str
    category: str
    severity: Severity
    team: str
    vendor: str | None
    sla_days: int
    due_date: str
    """Raised date + SLA days."""
    status: Literal["Assigned", "In Progress", "Closed", "Rejected - Misrouted"] = "Assigned"
    raised_by: str
    raised_at: str


class TicketSystem(Protocol):
    def raise_ticket(self, ticket: Ticket) -> None: ...

    def tickets(self) -> list[Ticket]: ...

    def ticket(self, ticket_id: str) -> Ticket | None: ...

    def for_feedback(self, feedback_id: str) -> list[Ticket]: ...


class LocalTicketSystem:
    """One JSON file per ticket. Raising the same ticket again overwrites it, so a retried step can't raise twice."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def raise_ticket(self, ticket: Ticket) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        target = self.path / f"{ticket.ticket_id}.json"
        partial = target.with_suffix(".part")
        partial.write_text(ticket.model_dump_json(indent=2), encoding="utf-8")
        partial.replace(target)

    def ticket(self, ticket_id: str) -> Ticket | None:
        path = self.path / f"{ticket_id}.json"
        return Ticket.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    def tickets(self) -> list[Ticket]:
        if not self.path.exists():
            return []
        found = [Ticket.model_validate_json(p.read_text(encoding="utf-8")) for p in self.path.glob("*.json")]
        return sorted(found, key=lambda t: (t.raised_at, t.ticket_id))

    def for_feedback(self, feedback_id: str) -> list[Ticket]:
        """The tickets raised from one feedback case."""
        return [t for t in self.tickets() if t.feedback_id == feedback_id]
