"""plg-api: adapts HTTP to the graph. No business logic of its own."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.openapi.utils import get_openapi
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, TypeAdapter
from sse_starlette import EventSourceResponse, ServerSentEvent

from plg.config import Settings
from plg.drafting.store import DraftStore
from plg.drafting.templates import TemplateLibrary
from plg.documents import ChunkLocation, DocumentLibrary, DocumentView
from plg.entities.open import LazyGraph
from plg.entities.store import GraphStore
from plg.events import RunEvent
from plg.data.warehouse import Warehouse
from plg.graph.build import build_graph
from plg.identity import UserCtx, load_personas
from plg.ingest.scans import SavedScans, TranscriptStore
from plg.llm import AnthropicLLMClient, LLMClient, Message
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


class RunRequest(BaseModel):
    message: str


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
) -> FastAPI:
    settings = settings or Settings.from_env()
    drafts = DraftStore()
    threads = ThreadStore(settings.threads_db)
    runs = RunRegistry()
    graph = build_graph(
        llm or AnthropicLLMClient(settings), searcher or LazySearcher(settings), entities=entities or LazyGraph(settings),
        warehouse=Warehouse(settings.records_db), templates=TemplateLibrary(settings.corpus_dir), drafts=drafts,
        settings=settings,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Checkpoints live beside thread ownership, so conversations survive a restart.
        async with AsyncSqliteSaver.from_conn_string(str(settings.threads_db)) as saver:
            graph.checkpointer = saver
            yield

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
            running=latest.question if latest and not latest.finished else None,
        )

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
