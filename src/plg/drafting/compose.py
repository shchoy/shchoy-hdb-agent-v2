"""Turn slot values into a checked draft: the filled letter, its open slots and personal-data flags."""

from __future__ import annotations

import uuid

from plg.drafting import pii, render
from plg.drafting.model import Draft, UnfilledSlot
from plg.drafting.templates import Template


def compose(
    template: Template, values: dict[str, str], reasons: dict[str, str], officer: set[str], names: set[str],
) -> tuple[Draft, bytes]:
    """The draft and its DOCX. Only the template's own slots are used; every other slot is listed as open."""
    values = {slot: v for slot, v in values.items() if slot in template.slots and v.strip()}
    unfilled = [
        UnfilledSlot(slot=slot, reason=reasons.get(slot) or "No value was supplied.")
        for slot in template.slots if slot not in values
    ]
    paragraphs = render.fill(template, values)
    draft = Draft(
        draft_id=str(uuid.uuid4()), template_id=template.template_id, template_title=template.title,
        template_version=template.version, slots=values, unfilled=unfilled,
        pii=pii.check(template.template_id, values, officer, names), html=render.to_html(paragraphs),
    )
    return draft, render.to_docx(template, paragraphs)
