"""Proposed actions and the officer's decision on them.

Anything that would leave the system exists only as a `ProposedAction` in graph state until its owner approves the
exact pending version through the `approval` interrupt. Only then does `execute_action` carry it out.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from plg.defects.classify import Candidate
from plg.defects.taxonomy import Severity
from plg.drafting.model import PiiFinding, UnfilledSlot
from plg.identity import Role

ActionType = Literal["send_letter", "raise_ticket"]
"""Grows with the flows that propose actions (record updates, glossary changes, ...)."""

Decision = Literal["approve", "edit", "reject"]

APPROVER_ROLES: dict[ActionType, list[Role]] = {
    "send_letter": ["officer", "estate_manager", "manager", "director", "legal"],
    "raise_ticket": ["officer", "estate_manager", "manager", "director"],
}
"""Who may approve (or edit) each action type. Analysts can draft letters and classify feedback but not send or raise
anything; anyone can reject their own proposal."""


class LetterPayload(BaseModel):
    """A letter filled from an approved template, as it would be sent."""

    kind: Literal["letter"] = "letter"
    draft_id: str
    template_id: str
    template_title: str
    template_version: str
    recipient: str
    slots: dict[str, str]
    unfilled: list[UnfilledSlot]
    pii: list[PiiFinding]


class TicketPayload(BaseModel):
    """An i-EMS ticket for classified feedback, as it would be raised."""

    kind: Literal["ticket"] = "ticket"
    feedback_id: str
    """The feedback case the ticket links back to: the case named in the question, or a new one for pasted feedback."""
    description: str
    """The feedback, as the maintenance team will read it."""
    unit_id: str | None
    category_code: str
    category: str
    severity: Severity
    team: str
    vendor: str | None
    sla_days: int
    """Completion SLA for the severity."""
    confidence: float
    low_confidence: bool
    rationale: str
    candidates: list[Candidate]


class ProposedAction(BaseModel):
    action_id: str
    """Stable across versions: a revised proposal keeps its ID and gets the next version."""
    version: int
    action_type: ActionType
    title: str
    payload: LetterPayload | TicketPayload
    preview: str
    """What will happen, as an escaped HTML fragment (the letter, the ticket)."""
    approver_roles: list[Role]
    proposed_by: str
    """Staff ID of the officer who asked for it: the only one who can decide on it."""
    proposed_at: str
    status: Literal["pending", "approved", "rejected"] = "pending"


class ApprovalDecision(BaseModel):
    """The officer's decision on one pending version of an action, as the `approval` interrupt receives it."""

    action_id: str
    version: int
    decision: Decision
    edits: dict[str, str] = Field(default_factory=dict)
    """Slot → new value (decision `edit`) of a letter, or ticket field → new value: the edited version is what is
    sent or raised."""
    reason: str = ""
    approver: str
    approver_role: Role

    def refusal(self, action: ProposedAction) -> str | None:
        """Why this decision can't be applied to `action`, or None if it can."""
        if (self.action_id, self.version) != (action.action_id, action.version) or action.status != "pending":
            return "That version of the action is not pending."
        if self.approver != action.proposed_by:
            return "Only the officer who asked for the action can decide on it."
        if self.decision != "reject" and self.approver_role not in action.approver_roles:
            return "Your role can't approve this action."
        return None


def upsert_actions(left: list[ProposedAction], right: list[ProposedAction]) -> list[ProposedAction]:
    """Actions fan in by ID: a newer copy (revised version, decided status) replaces the older one."""
    merged = {a.action_id: a for a in left}
    merged.update({a.action_id: a for a in right})
    return list(merged.values())


def pending(actions: list[ProposedAction]) -> list[ProposedAction]:
    return [a for a in actions if a.status == "pending"]

