"""Personal-data check on a draft. Deterministic: patterns for identity numbers, phone numbers and emails, plus,
for replies to the public, the names of tenants. The officer's own contact details are expected and pass."""

from __future__ import annotations

import re
from typing import Literal

from plg.drafting.model import PiiFinding

Kind = Literal["nric", "email", "phone", "tenant"]

NRIC = re.compile(r"(?<![A-Za-z0-9])[STFGM]\d{7}[A-Z](?![A-Za-z0-9])", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w-])(?:\+65[\s-]?)?[3689]\d{3}[\s-]?\d{4}(?!\d)")

PUBLIC_TEMPLATES = frozenset({"TPL-FBK-03"})
"""Templates addressed to members of the public, who must not be told about tenants."""


def digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)[-8:]


def check(
    template_id: str, values: dict[str, str], officer: set[str], tenant_names: set[str]
) -> list[PiiFinding]:
    """Findings per slot. `officer` holds the signing officer's email and phone, which may appear."""
    allowed = {o.lower() for o in officer} | {digits(o) for o in officer if digits(o)}
    findings: list[PiiFinding] = []
    for slot, value in values.items():
        found: list[tuple[Kind, str]] = []
        if NRIC.search(value):
            found.append(("nric", "Contains what looks like an NRIC/FIN number."))
        if any(m.group().lower() not in allowed for m in EMAIL.finditer(value)):
            found.append(("email", "Contains an email address that isn't the signing officer's."))
        if any(digits(m.group()) not in allowed for m in PHONE.finditer(value)):
            found.append(("phone", "Contains a phone number that isn't the signing officer's."))
        if template_id in PUBLIC_TEMPLATES:
            lowered = value.lower()
            if any(name.lower() in lowered for name in tenant_names):
                found.append(("tenant", "Names a tenant or their contact person in a reply to a member of the public."))
        findings += [PiiFinding(kind=kind, slot=slot, message=message) for kind, message in found]
    return findings
