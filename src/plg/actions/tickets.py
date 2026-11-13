"""i-EMS tickets as proposed actions: classified defect feedback becomes a `raise_ticket` proposal; an officer's edits
(category, severity, unit, description, feedback case) make the version raised."""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timedelta
from typing import get_args

from plg.actions.letters import now
from plg.actions.model import APPROVER_ROLES, ProposedAction, TicketPayload
from plg.defects.classify import Classification
from plg.defects.taxonomy import SLA_DAYS, Severity, Taxonomy
from plg.defects.tickets import Ticket

EDITABLE = ("category_code", "severity", "unit_id", "description", "feedback_id")
"""The ticket fields an officer can change; team, vendor and SLA follow from the category and severity."""
REQUIRED = {"category_code", "severity", "description", "feedback_id"}


def new_feedback_id() -> str:
    """A new case for feedback pasted without one (the POC's case numbers stay clear of PLG Records' FB-yyyy-nnnnn)."""
    return f"FB-NEW-{uuid.uuid4().hex[:8].upper()}"


def propose_ticket(
    found: Classification, description: str, feedback_id: str, unit_id: str | None, owner: str
) -> ProposedAction:
    """Raising an i-EMS ticket for a classified defect."""
    assert found.is_defect and found.sla_days is not None, "only maintenance defects become tickets"
    payload = TicketPayload(
        feedback_id=feedback_id, description=description, unit_id=unit_id, category_code=found.category_code,
        category=found.category, severity=found.severity, team=found.team, vendor=found.vendor,
        sla_days=found.sla_days, confidence=found.confidence, low_confidence=found.low_confidence,
        rationale=found.rationale, candidates=found.candidates,
    )
    return ProposedAction(
        action_id=str(uuid.uuid4()), version=1, action_type="raise_ticket", title=title(payload),
        payload=payload, preview=preview(payload), approver_roles=APPROVER_ROLES["raise_ticket"],
        proposed_by=owner, proposed_at=now(),
    )


def edit_errors(action: ProposedAction, edits: dict[str, str], taxonomy: Taxonomy) -> list[str]:
    """Why these edits can't be applied to the ticket (empty if they can)."""
    errors = [f"The ticket has no field {f}" for f in sorted(set(edits) - set(EDITABLE))]
    errors += [f"{f} can't be blank" for f in sorted(REQUIRED & set(edits)) if not edits[f].strip()]
    if (code := edits.get("category_code")) and not ((c := taxonomy.get(code)) and c.iems):
        errors.append(f"{code} is not an i-EMS defect category")
    if (severity := edits.get("severity")) and severity not in get_args(Severity):
        errors.append(f"Severity must be one of {', '.join(get_args(Severity))}")
    return errors


def edited(action: ProposedAction, edits: dict[str, str], taxonomy: Taxonomy) -> ProposedAction:
    """The ticket with the officer's edits applied: a new category re-routes it, a new severity sets its SLA."""
    old = action.payload
    assert isinstance(old, TicketPayload)
    update: dict[str, object] = {f: v.strip() or None for f, v in edits.items() if f in EDITABLE}
    if code := edits.get("category_code"):
        category = taxonomy.categories[code]
        update |= {"category": category.label, "team": category.team, "vendor": category.vendor}
        update.setdefault("severity", category.default_severity)
    severity: Severity = update.get("severity", old.severity)  # type: ignore[assignment]
    payload = old.model_copy(update={**update, "sla_days": SLA_DAYS[severity]})
    return action.model_copy(update={
        "version": action.version + 1, "payload": payload, "title": title(payload), "preview": preview(payload),
    })


def ticket_id(action: ProposedAction) -> str:
    """Stable for the action, so raising it again overwrites rather than duplicates."""
    return f"IEMS-{action.proposed_at[2:4]}{action.proposed_at[5:7]}-{action.action_id[:8].upper()}"


def to_ticket(action: ProposedAction, raised_by: str) -> Ticket:
    payload = action.payload
    assert isinstance(payload, TicketPayload)
    raised = now()
    due = (datetime.fromisoformat(raised) + timedelta(days=payload.sla_days)).date().isoformat()
    return Ticket(
        ticket_id=ticket_id(action), action_id=action.action_id, version=action.version,
        feedback_id=payload.feedback_id, description=payload.description, unit_id=payload.unit_id,
        category_code=payload.category_code, category=payload.category, severity=payload.severity,
        team=payload.team, vendor=payload.vendor, sla_days=payload.sla_days, due_date=due,
        raised_by=raised_by, raised_at=raised,
    )


def title(payload: TicketPayload) -> str:
    return f"Raise i-EMS ticket: {payload.category} ({payload.severity}) for {payload.team}"


def preview(payload: TicketPayload) -> str:
    """The ticket as i-EMS would show it, as an escaped HTML fragment."""
    rows = [
        ("Feedback case", payload.feedback_id), ("Unit", payload.unit_id or "Not given"),
        ("Category", f"{payload.category} ({payload.category_code})"), ("Priority", payload.severity),
        ("Team", payload.team), ("Vendor", payload.vendor or "None (handled by the team)"),
        ("SLA", f"{payload.sla_days} day{'s' if payload.sla_days != 1 else ''}"),
        ("Description", payload.description),
    ]
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows)
    return f"<h3>i-EMS ticket</h3><table>{body}</table>"
