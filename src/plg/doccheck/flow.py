"""`doc_check_flow`: the subgraph behind the `doc_check` specialist. load_application (PLG Records + its submission
bundle) → identify_files (each file by content; scans read by Claude, in parallel) → check_bundle (the application
type's checklist) → propose_notice (incomplete bundles only, needs a user). Sending the notice is only proposed: it
waits for the officer at the parent graph's `approval`."""

from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from plg.doccheck import notice, rules
from plg.doccheck.checklists import Checklists
from plg.doccheck.identify import Identified, identify
from plg.doccheck.model import DocCheck, Submission
from plg.drafting.model import Draft
from plg.drafting.templates import TemplateLibrary
from plg.entities.ids import find_ids, is_valid_id
from plg.identity import UserCtx
from plg.llm import LLMClient


class DocCheckInput(TypedDict, total=False):
    question: str
    user: UserCtx


class DocCheckOutput(TypedDict, total=False):
    result: DocCheck | None
    notice: Draft | None
    notice_docx: bytes
    summary: str
    """The specialist's finding, for merge."""


class DocCheckState(DocCheckInput, DocCheckOutput, total=False):
    application: rules.Application | None
    files: list[Path]
    identified: list[Identified]


DocCheckFlow = CompiledStateGraph[DocCheckState, Any, DocCheckInput, DocCheckOutput]

NO_APPLICATION = "The officer named no application (APP-yyyy-nnnn): ask which application's documents to check."
NOT_FOUND = "PLG Records hold no application {ids}."
NO_BUNDLE = "Application {app} ({label}) has no submission bundle to check: no submitted files were found for it."


def build_doc_check_flow(
    llm: LLMClient, checklists: Checklists, records_db: Path, submissions_dir: Path, templates: TemplateLibrary,
    today: Callable[[], dt.date] = dt.date.today,
) -> DocCheckFlow:
    async def load_application(state: DocCheckState) -> DocCheckState:
        ids = [i for i in find_ids(state["question"]) if is_valid_id("Application", i)]
        if not ids:
            return {"application": None, "result": None, "summary": NO_APPLICATION}
        app = await asyncio.to_thread(application, records_db, ids)
        if app is None:
            return {"application": None, "result": None, "summary": NOT_FOUND.format(ids=", ".join(ids))}
        folder = submissions_dir / app.application_id
        files = sorted(folder.glob("*.pdf")) if folder.is_dir() else []
        if not files:
            checklist = checklists.get(app.app_type)
            label = checklist.label if checklist else app.app_type
            return {"application": app, "files": [], "result": None, "summary": NO_BUNDLE.format(app=app.application_id, label=label)}
        return {"application": app, "files": files}

    async def identify_files(state: DocCheckState) -> DocCheckState:
        app = state["application"]
        assert app is not None
        found = await asyncio.gather(*(identify(llm, app.application_id, f, checklists.labels) for f in state["files"]))
        return {"identified": list(found)}

    def check_bundle(state: DocCheckState) -> DocCheckState:
        app = state["application"]
        assert app is not None
        checklist = checklists.get(app.app_type)
        if checklist is None:
            return {"result": None, "summary": f"There is no checklist for {app.app_type} applications."}
        found = rules.check(app, checklist, state["identified"], checklists.labels)
        return {"result": found, "summary": summary(found)}

    async def propose_notice(state: DocCheckState) -> DocCheckState:
        found, app, user = state["result"], state["application"], state["user"]
        assert found is not None and app is not None
        drafted = await asyncio.to_thread(notice.draft_notice, templates, records_db, found, app, user, today())
        if drafted is None:
            return {}
        draft, docx = drafted
        return {"notice": draft, "notice_docx": docx, "summary": state["summary"] + PROPOSED}

    def bundled(state: DocCheckState) -> str:
        return "identify_files" if state.get("files") else END

    def incomplete(state: DocCheckState) -> str:
        found = state.get("result")
        return "propose_notice" if found and not found.complete and state.get("user") else END

    graph = StateGraph(DocCheckState, input_schema=DocCheckInput, output_schema=DocCheckOutput)
    graph.add_node("load_application", load_application)
    graph.add_node("identify_files", identify_files)
    graph.add_node("check_bundle", check_bundle)
    graph.add_node("propose_notice", propose_notice)
    graph.add_edge(START, "load_application")
    graph.add_conditional_edges("load_application", bundled, ["identify_files", END])
    graph.add_edge("identify_files", "check_bundle")
    graph.add_conditional_edges("check_bundle", incomplete, ["propose_notice", END])
    graph.add_edge("propose_notice", END)
    return graph.compile()


PROPOSED = (
    "\nA missing-documents notice (TPL-DOC-02) listing these has been drafted and waits for the officer's approval; "
    "nothing is sent until then."
)


def summary(found: DocCheck) -> str:
    lines = [
        f"Document check of {found.app_type_label} application {found.application_id} ({found.tenant_name}, "
        f"unit {found.unit_id}), submitted {rules.long_date(found.submitted_date)}: "
        + ("complete: every required document was submitted and is valid." if found.complete else "incomplete."),
    ]
    for line in found.checklist:
        mark = {"ok": "✓", "missing": "✗", "problem": "✗", "not_submitted": "-"}[line.status]
        kind = "mandatory" if line.mandatory else "optional"
        detail = {
            "ok": f"submitted ({', '.join(line.files)})",
            "missing": "not submitted",
            "problem": f"{(line.problem or '').replace('_', ' ')}: {line.reason} ({', '.join(line.files)})",
            "not_submitted": "not submitted (optional)",
        }[line.status]
        lines.append(f"{mark} {line.label} ({line.doc_code}, {kind}): {detail}")
    others = [f.file for f in found.files if f.doc_code is None]
    if others:
        lines.append(f"Files that are none of the checklist documents: {', '.join(others)}.")
    return "\n".join(lines)


def application(records_db: Path, ids: list[str]) -> rules.Application | None:
    """The first named application that PLG Records hold, with its tenant, unit address and current tenancy."""
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as conn:
        for application_id in ids:
            row = conn.execute(
                """SELECT a.application_id, a.app_type, a.tenant_id, t.name, t.contact_person, a.unit_id, b.blk,
                          u.unit_no, b.street, b.postal_code, a.submitted_date, ta.end_date
                   FROM applications a
                   JOIN tenants t ON t.tenant_id = a.tenant_id
                   JOIN units u ON u.unit_id = a.unit_id
                   JOIN blocks b ON b.block_id = u.block_id
                   LEFT JOIN tenancies ta ON ta.tenancy_id = a.tenancy_id
                   WHERE a.application_id = ?""",
                (application_id,),
            ).fetchone()
            if row:
                return rules.Application(
                    application_id=row[0], app_type=row[1], tenant_id=row[2], tenant_name=row[3],
                    contact_person=row[4] or "", unit_id=row[5], blk=str(row[6]), unit_no=row[7],
                    unit_address=f"Blk {row[6]} {row[8]} {row[7]} Singapura {row[9]}",
                    submitted=dt.date.fromisoformat(row[10]),
                    tenancy_end=dt.date.fromisoformat(row[11]) if row[11] else None,
                )
    return None


def submissions(records_db: Path, submissions_dir: Path, checklists: Checklists) -> list[Submission]:
    """Every application with a submission bundle, newest first."""
    folders = {f.name: len(list(f.glob("*.pdf"))) for f in submissions_dir.iterdir() if f.is_dir()} if submissions_dir.is_dir() else {}
    if not folders:
        return []
    marks = ",".join("?" * len(folders))
    with sqlite3.connect(f"file:{records_db}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            f"""SELECT a.application_id, a.app_type, t.name, a.unit_id, a.submitted_date, a.status
                FROM applications a JOIN tenants t ON t.tenant_id = a.tenant_id
                WHERE a.application_id IN ({marks}) ORDER BY a.submitted_date DESC, a.application_id""",
            list(folders),
        ).fetchall()
    found = []
    for app_id, app_type, tenant, unit_id, submitted, status in rows:
        checklist = checklists.get(app_type)
        found.append(Submission(
            application_id=app_id, app_type=app_type, app_type_label=checklist.label if checklist else app_type,
            tenant_name=tenant, unit_id=unit_id, submitted_date=dt.date.fromisoformat(submitted), status=status or "",
            files=folders[app_id],
        ))
    return found
