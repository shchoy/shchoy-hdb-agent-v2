"""What drafting produces: a filled template, its open slots and any personal data found in it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class UnfilledSlot(BaseModel):
    slot: str
    reason: str


class PiiFinding(BaseModel):
    """Personal data that shouldn't be in the draft. Points at the slot; never repeats the value."""

    kind: Literal["nric", "email", "phone", "tenant"]
    slot: str
    message: str


class Draft(BaseModel):
    draft_id: str
    template_id: str
    template_title: str
    template_version: str
    slots: dict[str, str]
    unfilled: list[UnfilledSlot]
    pii: list[PiiFinding]
    html: str
    """The letter as an HTML fragment. Every slot value is escaped."""
