"""`plg` CLI. Drives the same graph as plg-api."""

from __future__ import annotations

import asyncio
import uuid

import typer
from dotenv import find_dotenv, load_dotenv

from plg.config import Settings
from plg.events import ErrorEvent, TokenEvent
from plg.graph.build import build_graph
from plg.llm import AnthropicLLMClient, LLMClient
from plg.runs import stream_run

app = typer.Typer(help="PLG Super-Librarian", no_args_is_help=True)


def make_llm(settings: Settings) -> LLMClient:
    return AnthropicLLMClient(settings)


@app.callback()
def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))


@app.command()
def ask(question: str) -> None:
    """Ask a question and stream the answer."""
    graph = build_graph(make_llm(Settings.from_env()))

    async def run() -> bool:
        async for event in stream_run(graph, str(uuid.uuid4()), question):
            if isinstance(event, TokenEvent):
                typer.echo(event.text, nl=False)
            elif isinstance(event, ErrorEvent):
                typer.echo()
                typer.echo(f"Error: {event.message} (run {event.run_id})", err=True)
                return False
        typer.echo()
        return True

    if not asyncio.run(run()):
        raise typer.Exit(code=1)


@app.command()
def serve() -> None:
    """Start plg-api."""
    from plg.api.app import serve as serve_api

    serve_api()
