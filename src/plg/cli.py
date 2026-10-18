"""`plg` CLI. Drives the same graph as plg-api."""

from __future__ import annotations

import asyncio
import uuid

import typer
from dotenv import find_dotenv, load_dotenv

from plg.config import Settings
from plg.events import ErrorEvent, TokenEvent
from plg.graph.build import build_graph
from plg.identity import load_personas
from plg.llm import AnthropicLLMClient, LLMClient, ScriptedLLMClient
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.glossary import load_glossary
from plg.runs import stream_run

app = typer.Typer(help="PLG Super-Librarian", no_args_is_help=True)
glossary_app = typer.Typer(help="Business glossary: versioned definitions.", no_args_is_help=True)
app.add_typer(glossary_app, name="glossary")


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


@app.command()
def openapi() -> None:
    """Print plg-api's OpenAPI document. The web app generates its types from it."""
    import json

    from plg.api.app import create_app

    # The contract doesn't depend on the model, so no API key is needed to print it.
    api = create_app(Settings.from_env(), llm=ScriptedLLMClient())
    typer.echo(json.dumps(api.openapi(), indent=2))


@glossary_app.command("list")
def glossary_list(
    all_versions: bool = typer.Option(False, "--all", help="Also list superseded and proposed versions."),
) -> None:
    """List glossary terms at their current version."""
    glossary = load_glossary()
    for concept in glossary.concepts():
        versions = glossary.versions(concept)
        if all_versions:
            for t in versions:
                typer.echo(f"{t.id:<36} {t.status:<10} {_period(t):<26} {t.pref_label}")
            continue
        t = glossary.current(concept) or versions[-1]
        earlier = sum(v.version < t.version for v in versions)
        history = f" ({earlier} earlier version{'s' if earlier > 1 else ''})" if earlier else ""
        typer.echo(f"{concept:<32} v{t.version:<3} from {t.effective_from or 'unrecorded'}  {t.pref_label}{history}")


@glossary_app.command("show")
def glossary_show(term: str) -> None:
    """Show a term's current definition and its history. TERM is an ID, label or synonym."""
    glossary = load_glossary()
    concept = glossary.find(term)
    if concept is None:
        typer.echo(f"No glossary term matches {term!r}. See `plg glossary list`.", err=True)
        raise typer.Exit(code=1)
    staff = load_personas(Settings.from_env().records_db)
    versions = glossary.versions(concept)
    current = glossary.current(concept)

    def describe(t: GlossaryTerm) -> None:
        owner = staff.get(t.owned_by)
        typer.echo(f"{t.id}  v{t.version}  {t.status}  {_period(t)}")
        typer.echo(f"  {t.definition}")
        if t.value:
            typer.echo(f"  Value: {t.value}")
        source = ", ".join(p for p in [t.source.document_id, t.source.locator] if p)
        typer.echo(f"  Source: {source}" + (f' - "{t.source.quote}"' if t.source.quote else ""))
        typer.echo(f"  Owner: {t.owned_by}" + (f" {owner.name}" if owner else ""))
        if t.supersedes:
            typer.echo(f"  Supersedes: {t.supersedes}")

    typer.echo(f"{versions[-1].pref_label} ({concept})")
    if current:
        typer.echo("\nCurrent:")
        describe(current)
    for heading, status in [("Proposed", "proposed"), ("History", "superseded")]:
        others = [t for t in reversed(versions) if t.status == status]
        if others:
            typer.echo(f"\n{heading}:")
            for t in others:
                describe(t)


def _period(t: GlossaryTerm) -> str:
    return f"{t.effective_from or 'unrecorded'} -> {t.effective_to or 'now'}"
