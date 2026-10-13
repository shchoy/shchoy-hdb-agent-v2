"""plg-api: adapts HTTP to the graph. No business logic of its own."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, TypeAdapter
from sse_starlette import EventSourceResponse, ServerSentEvent

from plg.config import Settings
from plg.events import RunEvent
from plg.graph.build import build_graph
from plg.identity import UserCtx, load_personas
from plg.llm import AnthropicLLMClient, LLMClient
from plg.runs import stream_run


class ThreadCreated(BaseModel):
    thread_id: str


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


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    graph = build_graph(llm or AnthropicLLMClient(settings))
    # Thread registry. Ownership and persistence across restarts arrive with later tickets.
    threads: set[str] = set()

    app = FastAPI(title="plg-api", version="0.1.0")

    app.state.personas = load_personas(settings.records_db)

    @app.get("/personas")
    async def list_personas(request: Request) -> list[UserCtx]:
        """Staff personas offered by the mock sign-in screen."""
        return list(request.app.state.personas.values())

    @app.get("/me")
    async def me(user: User) -> UserCtx:
        return user

    @app.post("/threads", status_code=201, dependencies=[Depends(current_user)])
    async def create_thread() -> ThreadCreated:
        thread_id = str(uuid.uuid4())
        threads.add(thread_id)
        return ThreadCreated(thread_id=thread_id)

    @app.post(
        "/threads/{thread_id}/runs",
        response_class=EventSourceResponse,
        responses={
            200: {
                "description": "Server-Sent Events; each frame's data is one RunEvent.",
                "content": {
                    "text/event-stream": {"schema": {"$ref": "#/components/schemas/RunEvent"}}
                },
            }
        },
    )
    async def create_run(thread_id: str, body: RunRequest, user: User) -> EventSourceResponse:
        if thread_id not in threads:
            raise HTTPException(status_code=404, detail="Thread not found")

        async def frames() -> AsyncIterator[ServerSentEvent]:
            async for event in stream_run(graph, thread_id, body.message, user):
                yield ServerSentEvent(
                    data=event.model_dump_json(), event=event.type, id=str(event.seq)
                )

        return EventSourceResponse(frames(), ping=settings.heartbeat_seconds)

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
