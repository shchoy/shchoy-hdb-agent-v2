"""plg-api: adapts HTTP to the graph. No business logic of its own."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.openapi.utils import get_openapi
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, TypeAdapter, model_validator
from sse_starlette import EventSourceResponse, ServerSentEvent

from plg.actions.audit import AuditEntry, AuditLog
from plg.actions import tickets
from plg.actions.letters import unknown_slots
from plg.actions.model import ApprovalDecision, Decision, LetterPayload, ProposedAction
from plg.actions.outbox import LocalOutbox, OutboxItem
from plg.config import Settings
from plg.defects.taxonomy import load_taxonomy
from plg.defects.tickets import LocalTicketSystem, Ticket
from plg.ontology.vocab import load_vocab
from plg.drafting.store import DraftStore
from plg.drafting.templates import TemplateLibrary
from plg.documents import ChunkLocation, DocumentLibrary, DocumentView
from plg.entities.local import LocalGraphStore
from plg.entities.open import LazyGraph, work_linker
from plg.entities.writer import GraphWriter
from plg.entities.store import GraphStore
from plg.events import RunEvent
from plg.data.warehouse import Warehouse
from plg.graph.build import build_graph
from plg.identity import UserCtx, load_personas
from plg.ingest.scans import SavedScans, TranscriptStore
from plg.llm import AnthropicLLMClient, LLMClient, Message
from plg.memory.service import MemoryService
from plg.memory.store import FlaggedByPolicy, MemoryStore, MemoryView, view
from plg.search.embed import LazyEmbedder
from plg.search.rerank import LazySearcher, Retriever
from plg.search.store import SearchStore
from plg.threads import RunBuffer, RunInProgress, RunRegistry, ThreadStore, ThreadSummary


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ThreadCreated(BaseModel):
    thread_id: str


class ThreadView(BaseModel):
    """A conversation rebuilt from its checkpoint: every exchange, and the summary standing in for older turns."""

    thread_id: str
    title: str
    messages: list[Message]
    summary: str
    running: str | None = None
    """The question still being answered, if a run is in progress: resume it with GET /threads/{id}/runs/latest."""
    pending: list[ProposedAction] = []
    """Actions waiting for the officer's decision (POST /threads/{id}/resume)."""


class RunRequest(BaseModel):
    message: str


class ResumeRequest(BaseModel):
    """The officer's decision on the exact pending version of an action."""

    action_id: str
    version: int
    decision: Decision
    edits: dict[str, str] = {}
    """Slot → new value (a letter) or ticket field → new value (category_code, severity, unit_id, description,
    feedback_id); required for `edit`, which sends or raises the edited version."""
    reason: str = ""
    """Why it was rejected; required for `reject`."""

    @model_validator(mode="after")
    def complete(self) -> ResumeRequest:
        if self.decision == "reject" and not self.reason.strip():
            raise ValueError("A rejection needs a reason")
        if self.decision == "edit" and not self.edits:
            raise ValueError("An edit needs at least one slot value")
        if self.decision != "edit" and self.edits:
            raise ValueError("Only an edit can change slot values")
        return self


class PendingApproval(ProposedAction):
    """A pending action and the conversation it waits in."""

    thread_id: str
    thread_title: str


class AuditRecord(AuditEntry):
    """A decision from the audit log and, unless it was a rejection, the outbox item it sent or the i-EMS ticket it
    raised."""

    sent: OutboxItem | None
    ticket: Ticket | None


class MemoryEdit(BaseModel):
    text: str | None = None
    """New wording. Editing makes the note yours and re-embeds it."""
    status: Literal["active", "retired"] | None = None
    """`retired` keeps the note but stops using it; `active` uses it again. A note flagged as conflicting with
    policy can't be switched back on (409): reword it (which clears the flag) or forget it."""


def current_user(
    request: Request,
    x_plg_user: Annotated[str | None, Header(description="Staff ID forwarded by the BFF")] = None,
) -> UserCtx:
    """POC identity: trusts the staff ID the BFF forwards over loopback."""
    personas: dict[str, UserCtx] = request.app.state.personas
    user = personas.get(x_plg_user or "")
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown or missing X-PLG-User")
    return user


User = Annotated[UserCtx, Depends(current_user)]


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    searcher: Retriever | None = None,
    store: SearchStore | None = None,
    entities: GraphStore | None = None,
    memory: MemoryStore | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    llm = llm or AnthropicLLMClient(settings)
    entities = entities or LazyGraph(settings)
    memory = memory or MemoryStore(lambda: _open_store(settings), LazyEmbedder(settings))
    link_work = None
    if isinstance(entities, LazyGraph):
        link_work = work_linker(entities.writer)
    elif isinstance(entities, LocalGraphStore):
        local = entities
        link_work = work_linker(lambda: GraphWriter(settings.graph_dir, local))
    learner = MemoryService(memory, llm, link_work)
    drafts = DraftStore()
    threads = ThreadStore(settings.threads_db)
    runs = RunRegistry()
    outbox = LocalOutbox(settings.outbox_dir)
    audit = AuditLog(settings.audit_log)
    ticket_system = LocalTicketSystem(settings.iems_dir)
    taxonomy = load_taxonomy(load_vocab())
    graph = build_graph(
        llm, searcher or LazySearcher(settings), entities=entities,
        warehouse=Warehouse(settings.records_db, settings.trackers_db), templates=TemplateLibrary(settings.corpus_dir), drafts=drafts,
        settings=settings, memory=learner, outbox=outbox, audit=audit,
        ticket_system=ticket_system, taxonomy=taxonomy,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Checkpoints live beside thread ownership, so conversations survive a restart.
        async with AsyncSqliteSaver.from_conn_string(str(settings.threads_db)) as saver:
            graph.checkpointer = saver
            yield
            await learner.drain()

    library = DocumentLibrary(
        lambda: store or _open_store(settings), settings.corpus_dir, SavedScans(TranscriptStore(settings.transcripts_dir))
    )

    app = FastAPI(title="plg-api", version="0.1.0", lifespan=lifespan)

    app.state.personas = load_personas(settings.records_db)

    @app.get("/personas")
    async def list_personas(request: Request) -> list[UserCtx]:
        """Staff personas offered by the mock sign-in screen."""
        return list(request.app.state.personas.values())

    @app.get("/me")
    async def me(user: User) -> UserCtx:
        return user

    def owned(thread_id: str, user: UserCtx) -> None:
        """Someone else's thread looks exactly like one that doesn't exist."""
        if not threads.owns(thread_id, user.staff_id):
            raise HTTPException(status_code=404, detail="Thread not found")

    @app.post("/threads", status_code=201)
    async def create_thread(user: User) -> ThreadCreated:
        return ThreadCreated(thread_id=threads.create(user.staff_id))

    @app.get("/threads")
    async def list_threads(user: User) -> list[ThreadSummary]:
        """The officer's own conversations, most recent first."""
        return threads.list(user.staff_id)

    @app.get("/threads/{thread_id}")
    async def get_thread(thread_id: str, user: User) -> ThreadView:
        owned(thread_id, user)
        values = (await graph.aget_state({"configurable": {"thread_id": thread_id}})).values
        title = next((t.title for t in threads.list(user.staff_id) if t.thread_id == thread_id), "")
        latest = runs.latest(thread_id)
        return ThreadView(
            thread_id=thread_id, title=title, messages=values.get("messages", []), summary=values.get("summary", ""),
            running=latest.question if latest and not latest.finished and latest.question else None,
            pending=await waiting(thread_id),
        )

    async def waiting(thread_id: str) -> list[ProposedAction]:
        """The actions the thread's checkpoint is paused on, so they survive a restart."""
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        return [ProposedAction.model_validate(a) for i in snapshot.interrupts for a in i.value]

    @app.get("/approvals")
    async def list_approvals(user: User, status: Literal["pending"] = "pending") -> list[PendingApproval]:
        """The officer's own actions waiting for a decision, across all their conversations, oldest first."""
        found = [
            PendingApproval(**action.model_dump(), thread_id=t.thread_id, thread_title=t.title)
            for t in threads.list(user.staff_id) for action in await waiting(t.thread_id)
        ]
        return sorted(found, key=lambda a: a.proposed_at)

    @app.get("/audit")
    async def audit_trail(user: User) -> list[AuditRecord]:
        """The officer's own decisions on proposed actions, newest first, each with the outbox item it sent or the
        i-EMS ticket it raised."""
        return [
            AuditRecord(
                **e.model_dump(), sent=outbox.item(e.outbox_id) if e.outbox_id else None,
                ticket=ticket_system.ticket(e.ticket_id) if e.ticket_id else None,
            )
            for e in audit.decided_by(user.staff_id)
        ]

    def memory_of(memory_id: str, user: UserCtx) -> MemoryView:
        """Someone else's memory looks exactly like one that doesn't exist."""
        item = memory.find(user.staff_id, memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return view(item)

    @app.get("/memory")
    async def list_memory(user: User) -> list[MemoryView]:
        """The officer's own memories, with where each came from."""
        memory.seed_profile(user)
        return [view(i) for i in memory.items(user.staff_id)]

    @app.get("/memory/{memory_id}")
    async def get_memory(memory_id: str, user: User) -> MemoryView:
        return memory_of(memory_id, user)

    @app.patch("/memory/{memory_id}")
    async def edit_memory(memory_id: str, body: MemoryEdit, user: User) -> MemoryView:
        memory_of(memory_id, user)
        try:
            edited = memory.edit(user.staff_id, memory_id, text=body.text, status=body.status)
        except FlaggedByPolicy as flagged:
            raise HTTPException(status_code=409, detail=str(flagged)) from None
        assert edited is not None
        return view(edited)

    @app.delete("/memory/{memory_id}", status_code=204)
    async def forget_memory(memory_id: str, user: User) -> Response:
        memory_of(memory_id, user)
        memory.forget(user.staff_id, memory_id)
        return Response(status_code=204)

    def sse(buffer: RunBuffer, after: int = 0) -> EventSourceResponse:
        async def frames() -> AsyncIterator[ServerSentEvent]:
            async for event in buffer.follow(after):
                yield ServerSentEvent(data=event.model_dump_json(), event=event.type, id=str(event.seq))

        return EventSourceResponse(frames(), ping=settings.heartbeat_seconds)

    run_stream_docs: dict[int | str, dict[str, Any]] = {
        200: {
            "description": "Server-Sent Events; each frame's data is one RunEvent.",
            "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/RunEvent"}}},
        }
    }

    @app.post("/threads/{thread_id}/runs", response_class=EventSourceResponse, responses=run_stream_docs)
    async def create_run(thread_id: str, body: RunRequest, user: User) -> EventSourceResponse:
        owned(thread_id, user)
        try:
            buffer = runs.start(graph, thread_id, body.message, user)
        except RunInProgress:
            raise HTTPException(status_code=409, detail="This conversation is still answering") from None
        threads.asked(thread_id, body.message)
        return sse(buffer)

    @app.post(
        "/threads/{thread_id}/resume", response_class=EventSourceResponse,
        responses={**run_stream_docs, 403: {"description": "Your role can't approve this action."},
                   409: {"description": "That version of the action isn't pending, or the thread is still answering."}},
    )
    async def resume_thread(thread_id: str, body: ResumeRequest, user: User) -> EventSourceResponse:
        """Approve, edit or reject the pending action. Only the thread's owner, holding an approver role for the
        action type, can decide, and only on the exact pending version; anything else changes nothing."""
        owned(thread_id, user)
        action = next((a for a in await waiting(thread_id) if a.action_id == body.action_id), None)
        if action is None or action.version != body.version:
            raise HTTPException(status_code=409, detail="That version of the action is not pending")
        if body.decision != "reject" and user.role not in action.approver_roles:
            raise HTTPException(status_code=403, detail="Your role can't approve this action")
        if isinstance(action.payload, LetterPayload):
            if body.decision == "edit" and (unknown := unknown_slots(action, body.edits)):
                raise HTTPException(status_code=422, detail=f"The letter has no slot {', '.join(unknown)}")
            blanked = {s for s, v in body.edits.items() if not v.strip()}
            still_open = sorted(({u.slot for u in action.payload.unfilled} | blanked) - (set(body.edits) - blanked))
            if body.decision != "reject" and still_open:
                raise HTTPException(status_code=422, detail=f"Fill the open slots before sending the letter: {', '.join(still_open)}")
        elif body.decision == "edit" and (errors := tickets.edit_errors(action, body.edits, taxonomy)):
            raise HTTPException(status_code=422, detail="; ".join(errors))
        decision = ApprovalDecision(**body.model_dump(), approver=user.staff_id, approver_role=user.role)
        try:
            buffer = runs.start(graph, thread_id, "", user, decision)
        except RunInProgress:
            raise HTTPException(status_code=409, detail="This conversation is still answering") from None
        return sse(buffer)

    @app.get("/threads/{thread_id}/runs/latest", response_class=EventSourceResponse, responses=run_stream_docs)
    async def resume_run(
        thread_id: str, user: User, last_event_id: Annotated[str | None, Header()] = None
    ) -> EventSourceResponse:
        """Re-attach to the latest run: its events after the `Last-Event-ID` the client last saw (default: all)."""
        owned(thread_id, user)
        buffer = runs.latest(thread_id)
        if buffer is None:
            raise HTTPException(status_code=404, detail="No run to resume")
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        return sse(buffer, after)

    @app.get("/documents/{doc_id}", dependencies=[Depends(current_user)])
    async def get_document(doc_id: str) -> DocumentView:
        """A source document as plain text blocks; markup in the file is never interpreted."""
        view = library.view(doc_id)
        if view is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return view

    @app.get(
        "/documents/{doc_id}/file",
        dependencies=[Depends(current_user)],
        response_class=FileResponse,
        responses={200: {"description": "The source file.", "content": {"application/octet-stream": {}}}},
    )
    async def get_document_file(doc_id: str) -> Response:
        """The source file. Only PDFs are shown inline; anything else downloads, sandboxed."""
        source = library.file(doc_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return FileResponse(
            source.path, media_type=source.content_type, filename=source.filename,
            content_disposition_type="inline" if source.kind == "pdf" else "attachment",
            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
        )

    @app.get("/documents/{doc_id}/chunks/{chunk_id}", dependencies=[Depends(current_user)])
    async def get_chunk_location(
        doc_id: str, chunk_id: str, start: int | None = None, end: int | None = None
    ) -> ChunkLocation:
        """Where the span `start:end` of a chunk's text (default: the whole chunk) sits in its document."""
        located = library.locate(doc_id, chunk_id, start, end)
        if located is None:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return located

    @app.get(
        "/drafts/{draft_id}/file",
        response_class=Response,
        responses={200: {"description": "The draft as a DOCX file.", "content": {DOCX: {}}}},
    )
    async def get_draft_file(draft_id: str, user: User) -> Response:
        """The draft as a DOCX file. Only the officer who asked for it can download it."""
        stored = drafts.get(draft_id, user.staff_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        return Response(
            stored.docx, media_type=DOCX,
            headers={"Content-Disposition": f'attachment; filename="{stored.filename}"', "X-Content-Type-Options": "nosniff"},
        )

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title, version=app.version, openapi_version=app.openapi_version,
                routes=app.routes,
            )
            schema["components"]["schemas"].update(run_event_schemas())
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


def _open_store(settings: Settings) -> SearchStore:
    from plg.search.lance import LanceSearchStore

    return LanceSearchStore(settings.search_db, dim=settings.embed_dim, vector_weight=settings.vector_weight)


def run_event_schemas() -> dict[str, Any]:
    """`RunEvent` and its variants as OpenAPI components, so the web app can generate SSE types."""
    schema = TypeAdapter(RunEvent).json_schema(ref_template="#/components/schemas/{model}")
    defs: dict[str, Any] = schema.pop("$defs")
    return {**defs, "RunEvent": schema}


def serve() -> None:
    """Entry point for `plg-api` and `plg serve`."""
    import uvicorn
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port)
