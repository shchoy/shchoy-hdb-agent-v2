"""Letters as proposed actions: a draft becomes a `send_letter` proposal; an officer's edits make the version sent."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from plg.actions.model import APPROVER_ROLES, LetterPayload, ProposedAction, pending
from plg.agents.drafting import officer_contacts, tenant_names
from plg.drafting.compose import compose
from plg.drafting.model import Draft
from plg.drafting.templates import TemplateLibrary

RECIPIENT_SLOTS = ("tenant_name", "provider_name", "contact_person")


def propose_letter(draft: Draft, owner: str, actions: list[ProposedAction]) -> ProposedAction:
    """Sending `draft`. A new draft from the same template revises the thread's pending letter (same ID, next
    version), so an approval of the version the officer saw can't send the newer one."""
    revised = next((a for a in pending(actions) if a.payload.template_id == draft.template_id), None)
    recipient = next((draft.slots[s] for s in RECIPIENT_SLOTS if draft.slots.get(s)), "the recipient")
    return ProposedAction(
        action_id=revised.action_id if revised else str(uuid.uuid4()),
        version=revised.version + 1 if revised else 1,
        action_type="send_letter",
        title=f"Send {draft.template_title} to {recipient}",
        payload=LetterPayload(
            draft_id=draft.draft_id, template_id=draft.template_id, template_title=draft.template_title,
            template_version=draft.template_version, recipient=recipient, slots=draft.slots,
            unfilled=draft.unfilled, pii=draft.pii,
        ),
        preview=draft.html,
        approver_roles=APPROVER_ROLES["send_letter"],
        proposed_by=owner,
        proposed_at=now(),
    )


def unknown_slots(action: ProposedAction, edits: dict[str, str]) -> list[str]:
    """Edited slots the letter's template doesn't have."""
    known = set(action.payload.slots) | {u.slot for u in action.payload.unfilled}
    return sorted(set(edits) - known)


def edited(action: ProposedAction, edits: dict[str, str], library: TemplateLibrary, records_db: Path) -> ProposedAction:
    """The letter with the officer's slot edits applied, re-rendered and re-checked: the next version."""
    template = library.get(action.payload.template_id)
    if template is None:
        raise LookupError(f"Template {action.payload.template_id} is no longer approved")
    officer = {c for c in officer_contacts(records_db, action.proposed_by) if c}
    reasons = {u.slot: u.reason for u in action.payload.unfilled}
    draft, _ = compose(template, {**action.payload.slots, **edits}, reasons, officer, tenant_names(records_db))
    letter = propose_letter(draft, action.proposed_by, [])
    return letter.model_copy(update={"action_id": action.action_id, "version": action.version + 1, "proposed_at": action.proposed_at})


def now() -> str:
    return datetime.now(UTC).isoformat()
