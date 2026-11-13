"""What a document check finds: each submitted file identified, and the application type's checklist ticked off."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel

Problem = Literal["expired", "wrong_unit", "illegible_scan"]
"""Why a submitted document can't be accepted. An illegible scan counts as not submitted."""

LineStatus = Literal["ok", "missing", "problem", "not_submitted"]
"""ok ✓; missing ✗ (a mandatory document nobody sent); problem ✗ (sent, but expired, for another unit or
illegible); not_submitted (an optional document nobody sent: no tick, no cross)."""


class FileCheck(BaseModel):
    """One file of the bundle, identified by what it says rather than its file name."""

    file: str
    doc_code: str | None
    """The checklist document it is, or None if it is none of them."""
    doc_label: str | None
    read_by: Literal["text", "scan"]
    """Read from its text layer, or by Claude from the page images (a scan)."""
    problem: Problem | None = None
    reason: str = ""


class ChecklistLine(BaseModel):
    doc_code: str
    label: str
    description: str
    mandatory: bool
    status: LineStatus
    files: list[str]
    problem: Problem | None = None
    reason: str = ""


class DocCheck(BaseModel):
    application_id: str
    app_type: str
    app_type_label: str
    tenant_id: str
    tenant_name: str
    unit_id: str
    unit_address: str
    submitted_date: dt.date
    checklist: list[ChecklistLine]
    files: list[FileCheck]
    missing: list[str]
    """Mandatory documents not submitted at all, by code."""
    problems: dict[str, Problem]
    """Submitted documents that can't be accepted, by code."""
    complete: bool


class Submission(BaseModel):
    """An application with a submission bundle, as the Document check screen offers it."""

    application_id: str
    app_type: str
    app_type_label: str
    tenant_name: str
    unit_id: str
    submitted_date: dt.date
    status: str
    files: int
