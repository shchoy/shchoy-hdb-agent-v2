"""Glossary changes as proposed actions (issue #25): a policy owner's change to a business definition becomes a
`proposed` version of the term inside an `approve_glossary_term` action that only the term owner can approve.

Checks are deterministic: the term exists and has a current version, the new version starts after the current one
did, and any new SQL binding passes the validator's dry run. Asking again in the same conversation revises the
pending proposal for that term (same action ID, next version).
"""

from __future__ import annotations

import html
import uuid
from datetime import date

from pydantic import BaseModel

from plg.actions.letters import now
from plg.actions.model import APPROVER_ROLES, GlossaryPayload, ProposedAction
from plg.data.semantic import SemanticLayer
from plg.data.sqlcheck import SqlRejected
from plg.data.warehouse import Warehouse
from plg.identity import UserCtx
from plg.ontology.changes import GlossaryVersion, TermSource
from plg.ontology.glossary import Glossary

EDITABLE = ("definition", "value", "effective_from")
"""What the term owner can change before approving; anything else is a new proposal."""


class ChangeRequest(BaseModel):
    """What the officer asked to change, as Claude read it from the conversation."""

    concept: str
    definition: str
    value: str | None = None
    effective_from: date | None = None
    reason: str
    source: TermSource | None = None
    sql: str | None = None


def propose_change(
    request: ChangeRequest,
    glossary: Glossary,
    layer: SemanticLayer,
    warehouse: Warehouse,
    staff: dict[str, UserCtx],
    user: UserCtx,
    actions: list[ProposedAction],
) -> ProposedAction | str:
    """The proposal, or why it can't be made."""
    concept = glossary.find(request.concept)
    if concept is None:
        return f"No glossary term matches {request.concept!r}, so there is nothing to change. New terms are added with `make ontology`."
    current = glossary.current(concept)
    if current is None:
        return f"{concept} has no current version to change."
    previous = GlossaryVersion.of(current)
    if not request.definition.strip():
        return "A glossary change needs the new definition."
    starts = request.effective_from or layer.as_of_default
    if problem := _start_problem(previous, starts):
        return problem
    sql = (request.sql or "").strip() or None
    if sql:
        try:
            warehouse.dry_run(sql, layer.as_of_default)
        except SqlRejected as e:
            return f"The proposed SQL binding was rejected: {e}"
    revised = next(
        (a for a in actions if a.status == "pending" and isinstance(a.payload, GlossaryPayload)
         and a.payload.term.concept == concept and a.proposed_by == user.staff_id),
        None,
    )
    action_id = revised.action_id if revised else str(uuid.uuid4())
    source = request.source if request.source and request.source.document_id else TermSource(
        document_id=None, locator=f"Glossary change {action_id}, proposed by {user.staff_id}: {request.reason.strip()}",
    )
    term = GlossaryVersion(
        id=f"{concept}_v{previous.version + 1}", concept=concept, version=previous.version + 1,
        pref_label=previous.pref_label, alt_labels=previous.alt_labels, definition=" ".join(request.definition.split()),
        value=request.value or None, source=source, owned_by=previous.owned_by, effective_from=starts,
        supersedes=previous.id, status="proposed",
    )
    inherited = layer.binding(previous.id)
    owner = staff.get(previous.owned_by)
    payload = GlossaryPayload(
        term=term, previous=previous, reason=request.reason.strip(), sql=sql,
        binding=sql or (inherited.sql.strip() if inherited else None), owner_name=owner.name if owner else previous.owned_by,
    )
    return ProposedAction(
        action_id=action_id, version=revised.version + 1 if revised else 1, action_type="approve_glossary_term",
        title=title(payload), payload=payload, preview=preview(payload),
        approver_roles=APPROVER_ROLES["approve_glossary_term"], proposed_by=user.staff_id,
        approvers=[previous.owned_by], proposed_at=revised.proposed_at if revised else now(),
    )


def _start_problem(previous: GlossaryVersion, starts: date) -> str | None:
    if previous.effective_from and starts <= previous.effective_from:
        return (
            f"The new version must start after {previous.effective_from}, when {previous.id} took effect "
            f"(proposed: {starts}). Definitions are never back-dated over the version in force."
        )
    return None


def edit_errors(action: ProposedAction, edits: dict[str, str]) -> list[str]:
    """Why the term owner's edits can't be applied (empty if they can)."""
    payload = action.payload
    assert isinstance(payload, GlossaryPayload)
    errors = [f"A glossary change has no editable field {f}" for f in sorted(set(edits) - set(EDITABLE))]
    if "definition" in edits and not edits["definition"].strip():
        errors.append("definition can't be blank")
    if "effective_from" in edits:
        try:
            starts = date.fromisoformat(edits["effective_from"].strip())
        except ValueError:
            errors.append("effective_from must be a date (YYYY-MM-DD)")
        else:
            if problem := _start_problem(payload.previous, starts):
                errors.append(problem)
    return errors


def edited(action: ProposedAction, edits: dict[str, str]) -> ProposedAction:
    """The proposal with the term owner's edits: the next version of the action."""
    payload = action.payload
    assert isinstance(payload, GlossaryPayload)
    update: dict[str, object] = {}
    if "definition" in edits:
        update["definition"] = " ".join(edits["definition"].split())
    if "value" in edits:
        update["value"] = edits["value"].strip() or None
    if "effective_from" in edits:
        update["effective_from"] = date.fromisoformat(edits["effective_from"].strip())
    changed = payload.model_copy(update={"term": payload.term.model_copy(update=update)})
    return action.model_copy(update={
        "version": action.version + 1, "payload": changed, "title": title(changed), "preview": preview(changed),
    })


def title(payload: GlossaryPayload) -> str:
    return f"Change glossary term {payload.term.pref_label}: {payload.previous.id} → {payload.term.id}"


def preview(payload: GlossaryPayload) -> str:
    """The change as an escaped HTML fragment: the definition in force and the proposed one, with dates and binding."""
    e = html.escape
    old, new = payload.previous, payload.term
    since = f"in force from {old.effective_from}" if old.effective_from else "in force since before records began"
    rows = [
        f"<h3>{e(new.pref_label)} ({e(new.concept)})</h3>",
        f"<p><strong>Now ({e(old.id)}, {e(since)}):</strong> {e(old.definition)}</p>",
        f"<p><strong>Proposed ({e(new.id)}, from {e(str(new.effective_from))}):</strong> {e(new.definition)}</p>",
    ]
    if new.value or old.value:
        rows.append(f"<p><strong>Value:</strong> {e(old.value or '-')} → {e(new.value or '-')}</p>")
    rows.append(f"<p><strong>Reason:</strong> {e(payload.reason)}</p>")
    rows.append(
        f"<p><strong>On approval:</strong> {e(old.id)} is superseded (in force until the day before) and kept.</p>"
    )
    if payload.binding:
        kept = "" if payload.sql else " (unchanged)"
        rows.append(f"<p><strong>SQL binding{kept}:</strong></p><pre>{e(payload.binding)}</pre>")
    rows.append(f"<p><strong>Term owner:</strong> {e(payload.owner_name)} ({e(new.owned_by)})</p>")
    return "\n".join(rows)
