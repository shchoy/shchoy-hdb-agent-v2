"""The eval targets: a golden question asked through the whole graph (as `plg ask` does), and the corpus audit.

A run's outcome is what its events showed: the specialists that ran (the route), the answer, its citations, the
data agent's queries, the draft, classification, document check, task digest, injections and proposed actions.
Nothing is written outside a scratch directory: no memory, no approvals (runs stop at the approval interrupt), no
question log; the audit writes its graph edges into a copy of the graph.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from plg.config import Settings
from plg.data.warehouse import Warehouse
from plg.entities.store import GraphStore
from plg.events import (
    CitationEvent, ClassificationEvent, DocCheckEvent, DraftEvent, ErrorEvent, InjectionEvent, NodeEvent,
    ProposedActionEvent, SqlTraceEvent, TasksEvent, TokenEvent,
)
from plg.graph.build import (
    CATEGORY_SUMMARY, DATA, DEFECT, DOC_CHECK, DRAFTING, GLOSSARY, KNOWLEDGE, MERGE, ROUTE, TASKS, build_graph,
)
from plg.graph.state import PLGGraph
from plg.identity import UserCtx, load_personas
from plg.llm import LLMClient
from plg.runs import stream_run
from plg.search.rerank import Retriever
from plg.search.store import SearchStore

SPECIALISTS = (KNOWLEDGE, DATA, DRAFTING, DEFECT, DOC_CHECK, TASKS, GLOSSARY, CATEGORY_SUMMARY)


class Outcome(BaseModel):
    """What one run produced, as its events showed it (the `outputs` of a LangSmith eval run)."""

    run_id: str | None = None
    intents: list[str] = Field(default_factory=list)
    """The specialists that ran: the route's decision."""
    answer: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    sql: list[dict[str, Any]] = Field(default_factory=list)
    drafts: list[dict[str, Any]] = Field(default_factory=list)
    classification: dict[str, Any] | None = None
    doc_check: dict[str, Any] | None = None
    tasks: dict[str, Any] | None = None
    injections: list[dict[str, Any]] = Field(default_factory=list)
    proposed: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class Harness:
    """Asks golden questions through a graph built like `plg ask`'s, in a scratch directory."""

    def __init__(
        self, llm: LLMClient, retriever: Retriever, settings: Settings, *,
        entities: GraphStore | None = None, scratch: Path | None = None,
    ) -> None:
        self.scratch = scratch or Path(tempfile.mkdtemp(prefix="plg-eval-"))
        self.settings = settings.model_copy(update={
            "threads_db": self.scratch / "threads.sqlite", "outbox_dir": self.scratch / "outbox",
            "audit_log": self.scratch / "audit.jsonl", "iems_dir": self.scratch / "iems",
            "feedback_log": self.scratch / "feedback.jsonl", "question_log": self.scratch / "questions.jsonl",
            "audit_reports_dir": self.scratch / "audit",
        })
        self.llm = llm
        self.personas = load_personas(settings.records_db, settings.developer_ids)
        self.graph: PLGGraph = build_graph(
            llm, retriever, entities=entities, settings=self.settings,
            warehouse=Warehouse(settings.records_db, settings.trackers_db),
        )

    def user(self, staff_id: str) -> UserCtx:
        return self.personas[staff_id]

    async def ask(self, question: str, user: str = "S05", *, route_only: bool = False) -> Outcome:
        """`route_only`: stop once the route's fan-out is known (the specialists of the next step have started, or
        merge has), so routing evals don't pay for answers."""
        out = Outcome()
        routed = False
        events = stream_run(self.graph, str(uuid.uuid4()), question, self.user(user), channel="cli")
        async for event in events:
            if route_only and routed and not (isinstance(event, NodeEvent) and event.status == "started"):
                break
            if isinstance(event, NodeEvent):
                if event.status == "started" and event.node in SPECIALISTS and event.node not in out.intents:
                    out.intents.append(event.node)
                if event.node == ROUTE and event.status == "finished":
                    routed = True
                if route_only and event.node == MERGE and event.status == "started":
                    break
            elif isinstance(event, TokenEvent):
                out.answer += event.text
            elif isinstance(event, CitationEvent):
                out.citations.append(event.model_dump(mode="json", include={"index", "doc_id", "chunk_id", "title", "quote"}))
            elif isinstance(event, SqlTraceEvent):
                out.sql.append(event.model_dump(mode="json", exclude={"type", "seq"}))
            elif isinstance(event, DraftEvent):
                out.drafts.append(event.model_dump(mode="json", include={"template_id", "slots", "unfilled", "pii"}))
            elif isinstance(event, ClassificationEvent):
                out.classification = event.model_dump(mode="json", exclude={"type", "seq"})
            elif isinstance(event, DocCheckEvent):
                out.doc_check = event.model_dump(mode="json", include={"application_id", "missing", "problems"})
            elif isinstance(event, TasksEvent):
                out.tasks = event.model_dump(mode="json", exclude={"type", "seq"})
            elif isinstance(event, InjectionEvent):
                out.injections.append(event.model_dump(mode="json", exclude={"type", "seq"}))
            elif isinstance(event, ProposedActionEvent):
                out.proposed.append(event.model_dump(mode="json", include={"action_id", "action_type", "title"}))
            elif isinstance(event, ErrorEvent):
                out.error = event.message
                out.run_id = event.run_id
            elif event.type == "done":
                out.run_id = event.run_id
        await cast(AsyncGenerator[Any, None], events).aclose()  # a route-only run stops here: its specialists are cancelled
        return out

    async def audit(self, store: SearchStore) -> dict[str, Any]:
        """`plg audit` over `store`, its edges written into a copy of the graph: the conflicts and duplicates found,
        as source-path pairs (a PLG Records side is its `record:<id>` passage)."""
        from plg.audit.audit import run_audit
        from plg.entities.open import open_graph
        from plg.entities.writer import GraphWriter
        from plg.ontology.changes import GlossaryChanges
        from plg.ontology.glossary import load_glossary
        from plg.ontology.vocab import load_vocab
        from plg.tracing import pii_masker

        graph_dir = self.scratch / "graph"
        if self.settings.graph_dir.exists() and not graph_dir.exists():
            shutil.copytree(self.settings.graph_dir, graph_dir)
        settings = self.settings.model_copy(update={"graph_dir": graph_dir})
        report = await run_audit(
            store, self.llm, GraphWriter(graph_dir, open_graph(settings)), settings, vocab=load_vocab(),
            glossary=GlossaryChanges(settings.glossary_changes).glossary(load_glossary()), now=datetime.now(UTC),
            mask=pii_masker(settings.records_db),
        )
        paths = {d.doc_id: d.source_path for d in store.documents()}

        def side(doc_id: str | None, chunk_id: str | None) -> str:
            return paths.get(doc_id or "", "") or (chunk_id or "")

        return {
            "conflicts": [{"topic": c.topic, "sides": sorted([side(c.a.doc_id, c.a.chunk_id), side(c.b.doc_id, c.b.chunk_id)])}
                          for c in report.conflicts],
            "duplicates": [sorted([paths.get(d.a.doc_id, ""), paths.get(d.b.doc_id, "")]) for d in report.duplicates],
            "rules": [{"rule": v.rule, "entity_ids": v.entity_ids} for v in report.rule_violations],
            "dropped": len(report.dropped),
        }
