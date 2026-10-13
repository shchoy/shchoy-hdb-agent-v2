"""plg-api: adapts HTTP to the graph. No business logic of its own."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette import EventSourceResponse, ServerSentEvent

from plg.config import Settings
from plg.graph.build import build_graph
from plg.llm import AnthropicLLMClient, LLMClient
from plg.runs import stream_run


class ThreadCreated(BaseModel):
    thread_id: str


class RunRequest(BaseModel):
    message: str


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    graph = build_graph(llm or AnthropicLLMClient(settings))
    # Thread registry. Ownership and persistence across restarts arrive with later tickets.
    threads: set[str] = set()

    app = FastAPI(title="plg-api", version="0.1.0")

    @app.post("/threads", status_code=201)
    async def create_thread() -> ThreadCreated:
        thread_id = str(uuid.uuid4())
        threads.add(thread_id)
        return ThreadCreated(thread_id=thread_id)

    @app.post("/threads/{thread_id}/runs")
    async def create_run(thread_id: str, body: RunRequest) -> EventSourceResponse:
        if thread_id not in threads:
            raise HTTPException(status_code=404, detail="Thread not found")

        async def frames() -> AsyncIterator[ServerSentEvent]:
            async for event in stream_run(graph, thread_id, body.message):
                yield ServerSentEvent(
                    data=event.model_dump_json(), event=event.type, id=str(event.seq)
                )

        return EventSourceResponse(frames(), ping=settings.heartbeat_seconds)

    return app


def serve() -> None:
    """Entry point for `plg-api` and `plg serve`."""
    import uvicorn
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port)
