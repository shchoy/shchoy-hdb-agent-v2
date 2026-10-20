"""The `drafting` agent: picks the approved template for a requested letter and fills its slots from PLG Records.

Its tools only read (templates, records) and propose: `submit_draft` records a draft for the officer to preview and
download. Nothing is sent, and drafting creates no outbox item. Slots it can't fill are listed, never invented, and
the filled draft gets a personal-data check.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from plg.agents.data import result_text
from plg.agents.runtime import Tool, run_agent
from plg.data.semantic import SemanticLayer
from plg.data.sqlcheck import SqlRejected
from plg.data.warehouse import Warehouse
from plg.drafting import pii, render
from plg.drafting.model import Draft, UnfilledSlot
from plg.drafting.store import DraftStore
from plg.drafting.templates import Template, TemplateLibrary
from plg.identity import UserCtx
from plg.llm import AgentMessage, LLMClient

NODE = "drafting"

SYSTEM = """\
You are the drafting specialist of the PLG Super-Librarian. An officer of the Properties & Land Group asks for a \
standard letter; you choose the right approved template and fill its slots with values from PLG Records.

How to work:
1. Pick the template whose purpose matches the request (listed below). Call get_template to read its wording and slots.
2. Look up every value you need with lookup_records (one read-only SELECT over PLG Records; DuckDB SQL). Tenants, \
tenancies, units and blocks (for addresses), rent_invoices (unpaid invoices: status 'Unpaid'), applications and \
application_documents (what was submitted: mandatory = 1 and submitted = 0 means missing), feedback_cases and \
iems_tickets. Never invent a value: figures, dates, names, references and addresses come from the records or from \
the officer's request.
3. Call submit_draft with the template ID and a value for each slot. List under `unfilled` every slot you could not \
fill, with the reason, and leave it out of `slots`. Don't fill a slot with a placeholder or a guess. If you submit \
again, the new draft replaces the old one.
4. Finish with one or two sentences: which template you used, and what the officer needs to supply.

Rules:
- The approved wording must not change: you only supply slot values.
- The letter is signed by the officer you are working for (below); use their name, phone and email for the officer \
slots. `letter_ref` has no source in PLG Records: fill it only if the officer gave one.
- Money is Singapore dollars, GST included, formatted like S$3,924.00. Write dates like 14 October 2026. \
Today is {today}; "14 days from the date of this letter" is computed from it.
- Multi-line values (an invoice table, a list of documents) use one line per item.
- Put only what the template asks for into a slot. In a reply to a member of the public never mention tenants.
- Nothing you do sends anything.

Approved templates:
{templates}

Tables (all columns are in the database; DESCRIBE is not available):
{tables}"""


class TemplateInput(BaseModel):
    template_id: str


class LookupInput(BaseModel):
    plan: str = ""
    sql: str


class SlotNote(BaseModel):
    slot: str
    reason: str = ""


class SubmitInput(BaseModel):
    template_id: str
    slots: dict[str, Any] = {}
    unfilled: list[SlotNote] = []


class DraftingResult(BaseModel):
    text: str
    draft: Draft | None


def describe(template: Template) -> str:
    return f"- {template.template_id} v{template.version} ({template.title}): {template.purpose}. Slots: {', '.join(template.slots)}"


def officer_contacts(records_db: Path, staff_id: str) -> tuple[str, str]:
    """Email and phone of the signing officer, from `staff` (which the agent's SQL can't read)."""
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as con:
        row = con.execute("SELECT email, phone FROM staff WHERE staff_id = ?", [staff_id]).fetchone()
    return (row[0], row[1]) if row else ("", "")


def tenant_names(records_db: Path) -> set[str]:
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as con:
        rows = con.execute("SELECT name, contact_person FROM tenants").fetchall()
    return {n.strip() for row in rows for n in row if n and len(n.strip()) > 4}


def template_tool(library: TemplateLibrary) -> Tool:
    async def run(raw: dict[str, Any]) -> str:
        try:
            args = TemplateInput.model_validate(raw)
        except ValidationError as e:
            return f"Invalid arguments: {e.errors()[0]['msg']}"
        template = library.get(args.template_id)
        if template is None:
            return unknown(library, args.template_id)
        return f"{describe(template)}\n\nApproved wording ({{{{ slot }}}} = a slot to fill):\n\n{template.wording()}"

    return Tool(
        name="get_template",
        description="The approved wording and required slots of a letter template.",
        input_schema={
            "type": "object",
            "properties": {"template_id": {"type": "string", "description": "e.g. TPL-REM-01"}},
            "required": ["template_id"],
        },
        run=run,
    )


def unknown(library: TemplateLibrary, template_id: str) -> str:
    return f"No approved template {template_id!r}. Approved templates:\n" + "\n".join(describe(t) for t in library.all())


def lookup_tool(warehouse: Warehouse, layer: SemanticLayer) -> Tool:
    async def run(raw: dict[str, Any]) -> str:
        try:
            args = LookupInput.model_validate(raw)
        except ValidationError as e:
            return f"Invalid arguments: {e.errors()[0]['msg']}"
        try:
            result = await asyncio.to_thread(warehouse.run, args.sql, layer.as_of_default)
        except SqlRejected as e:
            return f"Rejected: {e}"
        return result_text(result, [])

    return Tool(
        name="lookup_records",
        description=(
            "Run one read-only SELECT over PLG Records (DuckDB SQL) and get the rows, tab-separated, or the reason "
            "it was rejected."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "What you are looking up."},
                "sql": {"type": "string", "description": "A single SELECT statement."},
            },
            "required": ["sql"],
        },
        run=run,
    )


def submit_tool(
    library: TemplateLibrary, drafts: list[tuple[Draft, bytes]],
    officer: set[str], names: set[str],
) -> Tool:
    async def run(raw: dict[str, Any]) -> str:
        try:
            args = SubmitInput.model_validate(raw)
        except ValidationError as e:
            return f"Invalid arguments: {e.errors()[0]['msg']}"
        template = library.get(args.template_id)
        if template is None:
            return unknown(library, args.template_id)
        values = {
            slot: str(v).strip() for slot, v in args.slots.items()
            if slot in template.slots and v is not None and str(v).strip()
        }
        reasons = {n.slot: n.reason for n in args.unfilled}
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
        drafts.append((draft, render.to_docx(template, paragraphs)))
        return summary(draft)

    return Tool(
        name="submit_draft",
        description=(
            "Record the filled template as a draft for the officer to preview and download. Nothing is sent. "
            "Returns what is still open and any personal-data flags."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "template_id": {"type": "string"},
                "slots": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Slot name → value."},
                "unfilled": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"slot": {"type": "string"}, "reason": {"type": "string"}},
                        "required": ["slot", "reason"],
                    },
                    "description": "Slots you could not fill, with why.",
                },
            },
            "required": ["template_id", "slots"],
        },
        run=run,
    )


def summary(draft: Draft) -> str:
    """What is left for the officer, in words. Also what the agent is told after submitting."""
    lines = [f"Draft made from {draft.template_id} ({draft.template_title}). Nothing has been sent."]
    if draft.unfilled:
        lines.append("Slots still to fill: " + "; ".join(f"{u.slot} ({u.reason})" for u in draft.unfilled) + ".")
    else:
        lines.append("Every slot is filled.")
    if draft.pii:
        lines.append("Personal data to remove before approving: " + "; ".join(f"{p.slot}: {p.message}" for p in draft.pii))
    return "\n".join(lines)


async def answer(
    llm: LLMClient,
    warehouse: Warehouse,
    layer: SemanticLayer,
    library: TemplateLibrary,
    store: DraftStore,
    messages: list[AgentMessage],
    user: UserCtx | None,
) -> DraftingResult:
    drafts: list[tuple[Draft, bytes]] = []
    email, phone = officer_contacts(warehouse.records_db, user.staff_id) if user else ("", "")
    officer = {c for c in (email, phone) if c}
    signer = f"You are drafting for {user.name}, {user.title} (email {email}, phone {phone})." if user else ""
    tables = "\n".join(f"- {name}: {note}" for name, note in layer.tables.items())
    result = await run_agent(
        llm,
        node=NODE,
        system=SYSTEM.format(
            today=layer.as_of_default, templates="\n".join(describe(t) for t in library.all()), tables=tables,
        ),
        context=signer,
        tools=[
            template_tool(library),
            lookup_tool(warehouse, layer),
            submit_tool(library, drafts, officer, tenant_names(warehouse.records_db)),
        ],
        messages=messages,
    )
    draft = None
    if drafts:  # a later submission replaces an earlier one: only the last is kept for download
        draft, docx_bytes = drafts[-1]
        store.add(user.staff_id if user else "", draft, docx_bytes)
    return DraftingResult(text=f"{result.text}\n\n{summary(draft)}".strip() if draft else result.text, draft=draft)
