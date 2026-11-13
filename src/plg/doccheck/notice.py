"""The missing-documents notice (approved template TPL-DOC-02), filled from the check and PLG Records. It lists
exactly what is missing or can't be accepted. The letter reference has no source in PLG Records: it stays open
for the officer to give, as in every drafted letter."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from plg.agents.drafting import officer_contacts, tenant_names
from plg.doccheck.model import DocCheck
from plg.doccheck.rules import Application, long_date
from plg.drafting.compose import compose
from plg.drafting.model import Draft
from plg.drafting.templates import TemplateLibrary
from plg.identity import UserCtx

TEMPLATE_ID = "TPL-DOC-02"
REPLY_DAYS = 14
REASONS = {"letter_ref": "PLG Records hold no letter reference: give one before sending."}


def outstanding(found: DocCheck) -> str:
    """One line per document the applicant still owes: missing ones, then those that can't be accepted."""
    lines = [f"- {line.description} (not submitted)" for line in found.checklist if line.status == "missing"]
    lines += [f"- {line.description}: {line.reason}" for line in found.checklist if line.status == "problem"]
    return "\n".join(lines)


def draft_notice(
    library: TemplateLibrary, records_db: Path, found: DocCheck, app: Application, officer: UserCtx, today: dt.date,
) -> tuple[Draft, bytes] | None:
    template = library.get(TEMPLATE_ID)
    if template is None:
        return None
    email, phone = officer_contacts(records_db, officer.staff_id)
    values = {
        "letter_date": long_date(today),
        "tenant_name": app.tenant_name,
        "contact_person": app.contact_person,
        "application_id": found.application_id,
        "application_type": found.app_type_label.upper(),
        "unit_address": app.unit_address,
        "missing_documents_list": outstanding(found),
        "submit_by_date": long_date(today + dt.timedelta(days=REPLY_DAYS)),
        "officer_name": officer.name,
        "officer_email": email,
    }
    return compose(template, values, REASONS, {c for c in (email, phone) if c}, tenant_names(records_db))
