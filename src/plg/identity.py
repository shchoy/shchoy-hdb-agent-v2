"""POC identity: staff personas from PLG Records. Production replaces this with Entra ID OIDC."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Role = Literal["director", "manager", "estate_manager", "officer", "analyst", "legal"]


class UserCtx(BaseModel):
    """The signed-in staff member. Approver roles and memory isolation key off this."""

    staff_id: str
    name: str
    title: str
    dept: str
    role: Role


def role_for(title: str) -> Role:
    """The `staff` table has no role column, so the role is derived from the job title."""
    if title.startswith(("Director", "Deputy Director")):
        return "director"
    if title.startswith("Estate Manager"):
        return "estate_manager"
    if "Manager" in title:
        return "manager"
    if "Analyst" in title:
        return "analyst"
    if title.startswith("Legal"):
        return "legal"
    return "officer"


def load_personas(records_db: Path) -> dict[str, UserCtx]:
    """Every staff member, keyed by staff ID, in staff ID order."""
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT staff_id, name, title, dept FROM staff ORDER BY staff_id"
        ).fetchall()
    return {
        staff_id: UserCtx(
            staff_id=staff_id, name=name, title=title, dept=dept, role=role_for(title)
        )
        for staff_id, name, title, dept in rows
    }
