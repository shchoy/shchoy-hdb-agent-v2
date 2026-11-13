"""The checklist rules, applied to what each file says:

- business profiles must be dated within 3 months of submission;
- an insurance certificate must be in force when the new term starts (renewals: the day after the current tenancy
  expires), otherwise on the submission date; licences and contractor registrations must not have lapsed;
- documents must name the application's unit (unit ID or unit address);
- an illegible scan can't be accepted: its line is crossed as a problem (not counted as missing, since
  something was sent) and the notice asks for it again.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from plg.doccheck.checklists import Checklist
from plg.doccheck.identify import Identified
from plg.doccheck.model import ChecklistLine, DocCheck, FileCheck, LineStatus, Problem


@dataclass(frozen=True)
class Application:
    application_id: str
    app_type: str
    tenant_id: str
    tenant_name: str
    contact_person: str
    unit_id: str
    blk: str
    unit_no: str
    """As in the unit's address, e.g. `#01-08`."""
    unit_address: str
    submitted: dt.date
    tenancy_end: dt.date | None
    """The current tenancy's expiry (renewals, assignments, ...); None for a new tenancy."""


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}
DATE = r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
UNIT_ID = re.compile(r"\bU-[A-Z]{2}\d{3}-\d{2}-\d{2}\b")
ADDRESS = re.compile(r"\bBlk\s+(\d+)\b[^#]{0,80}?(#\d{2}-\d{2})")
OWN_ADDRESS_ONLY = {"BIZ2", "NRIC"}
"""Documents about another party (the assignee, a person), whose addresses needn't be the unit's."""


def parse_date(text: str) -> dt.date | None:
    day, month, year = text.split()
    number = MONTHS.get(month[:3].lower())
    try:
        return dt.date(int(year), number, int(day)) if number else None
    except ValueError:
        return None


def long_date(day: dt.date) -> str:
    return f"{day.day} {day:%B %Y}"


def months_before(day: dt.date, months: int) -> dt.date:
    year, month = divmod(day.month - 1 - months, 12)
    month += 1
    year += day.year
    for d in (day.day, 30, 29, 28):
        try:
            return dt.date(year, month, d)
        except ValueError:
            continue
    raise ValueError(day)


def find_date(text: str, label: str) -> dt.date | None:
    m = re.search(label + r"\W*" + DATE, text)
    return parse_date(m.group(1)) if m else None


def find_period_end(text: str, label: str) -> dt.date | None:
    m = re.search(label + r"\W*" + DATE + r"\s+to\s+" + DATE, text)
    return parse_date(m.group(2)) if m else None


def doc_code(found: Identified, app: Application) -> str | None:
    """Business profiles in an assignment: the assignor's is BIZ, any other company's is the assignee's (BIZ2)."""
    if found.doc_code == "BIZ" and app.app_type == "ASSIGNMENT":
        name = re.search(r"\bName\W*\n?\s*(.+)", found.text)
        if name and name.group(1).strip().lower() != app.tenant_name.lower():
            return "BIZ2"
    return found.doc_code


def problem(found: Identified, code: str | None, app: Application) -> tuple[Problem | None, str]:
    if not found.legible:
        return "illegible_scan", "The scan can't be read, so it counts as not submitted."
    if code is None:
        return None, ""
    if code not in OWN_ADDRESS_ONLY:
        others = sorted({u for u in UNIT_ID.findall(found.text) if u != app.unit_id})
        if others:
            return "wrong_unit", f"It names unit {', '.join(others)}, not {app.unit_id}."
        addresses = sorted({f"Blk {b} {n}" for b, n in ADDRESS.findall(found.text) if (b, n) != (app.blk, app.unit_no)})
        if addresses:
            return "wrong_unit", f"It names {', '.join(addresses)}, not Blk {app.blk} {app.unit_no} ({app.unit_id})."
    return expiry(found.text, code, app)


def expiry(text: str, code: str, app: Application) -> tuple[Problem | None, str]:
    submitted = long_date(app.submitted)
    if code in ("BIZ", "BIZ2"):
        extract = find_date(text, r"Date of extract")
        oldest = months_before(app.submitted, 3)
        if extract and extract < oldest:
            return "expired", f"Extracted on {long_date(extract)}, more than 3 months before the application ({submitted})."
    elif code == "INS":
        end = find_period_end(text, r"Period of insurance")
        if end and app.app_type == "RENEWAL" and app.tenancy_end:
            starts = app.tenancy_end + dt.timedelta(days=1)
            if end < starts:
                return "expired", f"The cover ends on {long_date(end)}, before the new term starts on {long_date(starts)}."
        elif end and end < app.submitted:
            return "expired", f"The cover ended on {long_date(end)}, before the application ({submitted})."
    elif code == "LIC":
        end = find_period_end(text, r"Valid")
        if end and end < app.submitted:
            return "expired", f"The licence lapsed on {long_date(end)}, before the application ({submitted})."
    elif code == "CON":
        end = find_date(text, r"Valid until")
        if end and end < app.submitted:
            return "expired", f"The registration lapsed on {long_date(end)}, before the application ({submitted})."
    return None, ""


def check(app: Application, checklist: Checklist, found: list[Identified], labels: dict[str, str]) -> DocCheck:
    files: list[FileCheck] = []
    for f in found:
        code = doc_code(f, app)
        issue, reason = problem(f, code, app)
        files.append(FileCheck(
            file=f.file, doc_code=code, doc_label=labels.get(code) if code else None,
            read_by=f.read_by, problem=issue, reason=reason,
        ))
    lines: list[ChecklistLine] = []
    for required in checklist.documents:
        mine = [f for f in files if f.doc_code == required.doc_code]
        good = [f for f in mine if f.problem is None]
        bad = next((f for f in mine if f.problem), None)
        status: LineStatus = "ok" if good else "problem" if bad else "missing" if required.mandatory else "not_submitted"
        lines.append(ChecklistLine(
            doc_code=required.doc_code, label=required.label, description=required.description,
            mandatory=required.mandatory, status=status, files=[f.file for f in mine],
            problem=bad.problem if bad and not good else None, reason=bad.reason if bad and not good else "",
        ))
    missing = sorted(line.doc_code for line in lines if line.status == "missing")
    problems = {line.doc_code: line.problem for line in lines if line.problem}
    return DocCheck(
        application_id=app.application_id, app_type=app.app_type, app_type_label=checklist.label,
        tenant_id=app.tenant_id, tenant_name=app.tenant_name, unit_id=app.unit_id, unit_address=app.unit_address,
        submitted_date=app.submitted, checklist=lines, files=files, missing=missing, problems=problems,
        complete=not missing and not problems,
    )
