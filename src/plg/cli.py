"""`plg` CLI. Drives the same graph as plg-api."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import date

import typer
from dotenv import find_dotenv, load_dotenv

from plg.config import Settings
from plg.entities.open import LazyGraph, open_graph
from plg.entities.spine import write_spine
from plg.events import CitationEvent, ErrorEvent, TokenEvent
from plg.graph.build import build_graph
from plg.identity import load_personas
from plg.llm import AnthropicLLMClient, LLMClient, ScriptedLLMClient
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.glossary import load_glossary
from plg.runs import stream_run
from plg.search.embed import Embedder, VoyageEmbedder
from plg.search.models import DocStatus, SearchFilter
from plg.search.rerank import LazySearcher, Reranker
from plg.search.rerank import make_reranker as build_reranker

app = typer.Typer(help="PLG Super-Librarian", no_args_is_help=True)
graph_app = typer.Typer(help="Entity graph built from PLG Records.", no_args_is_help=True)
app.add_typer(graph_app, name="graph")
glossary_app = typer.Typer(help="Business glossary: versioned definitions.", no_args_is_help=True)
app.add_typer(glossary_app, name="glossary")


def make_llm(settings: Settings) -> LLMClient:
    return AnthropicLLMClient(settings)


def make_embedder(settings: Settings) -> Embedder:
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        typer.echo("VOYAGE_API_KEY is not set. Add it to .env at the repo root.", err=True)
        raise typer.Exit(code=1)
    return VoyageEmbedder(settings, api_key)


def make_reranker(settings: Settings) -> Reranker:
    return build_reranker(settings)


@app.callback()
def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))


@app.command()
def ask(question: str) -> None:
    """Ask a question and stream the answer."""
    settings = Settings.from_env()
    graph = build_graph(make_llm(settings), LazySearcher(settings), entities=LazyGraph(settings))

    async def run() -> bool:
        citations: list[CitationEvent] = []
        async for event in stream_run(graph, str(uuid.uuid4()), question):
            if isinstance(event, TokenEvent):
                typer.echo(event.text, nl=False)
            elif isinstance(event, CitationEvent):
                citations.append(event)
            elif isinstance(event, ErrorEvent):
                typer.echo()
                typer.echo(f"Error: {event.message} (run {event.run_id})", err=True)
                return False
        typer.echo()
        if citations:
            typer.echo("\nSources:")
        for c in citations:
            typer.echo(f"[{c.index}] {c.title} - {c.location} ({c.chunk_id})\n    \"{c.quote}\"")
        return True

    if not asyncio.run(run()):
        raise typer.Exit(code=1)


@app.command()
def sync(
    full: bool = typer.Option(False, "--full", help="Drop the index and re-ingest everything."),
) -> None:
    """Ingest changed corpus documents (SharePoint and Lotus Notes mocks) into the search index."""
    from plg.ingest.metadata import load_entity_spine
    from plg.ingest.scans import ScanReader, TranscriptStore
    from plg.ingest.sources import DocumentSource, LotusNotesSource, SharePointSource
    from plg.ingest.sync import sync as run_sync
    from plg.search.lance import LanceSearchStore

    settings = Settings.from_env()
    embedder = make_embedder(settings)
    if full and settings.search_db.exists():
        shutil.rmtree(settings.search_db)
    store = LanceSearchStore(settings.search_db, dim=embedder.dim, vector_weight=settings.vector_weight)
    entities, tagger = load_entity_spine(settings.records_db)
    sources: list[DocumentSource] = [SharePointSource(settings.corpus_dir), LotusNotesSource(settings.corpus_dir)]
    scans = ScanReader(make_llm(settings), TranscriptStore(settings.transcripts_dir))
    report = run_sync(store, embedder, sources, entities, tagger, scans)

    typer.echo(
        f"Added {len(report.added)}, updated {len(report.updated)}, unchanged {len(report.unchanged)}, "
        f"skipped {len(report.skipped)} documents; wrote {report.chunks_written} chunks."
    )
    for path in report.superseded:
        typer.echo(f"Superseded: {path}")
    for skipped in report.skipped:
        typer.echo(f"Skipped: {skipped.rel_path} ({skipped.reason})")


@app.command()
def search(
    query: str,
    k: int = typer.Option(8, help="Number of results."),
    status: DocStatus | None = typer.Option(None, help="current or superseded."),
    doc_type: list[str] = typer.Option([], "--type", help="Document type, e.g. policy (repeatable)."),
    in_force_on: str | None = typer.Option(None, help="Only documents in force on this date (YYYY-MM-DD)."),
) -> None:
    """Hybrid search of the index with rerank, for checking what `plg sync` indexed."""
    from plg.search.lance import LanceSearchStore
    from plg.search.rerank import Searcher

    settings = Settings.from_env()
    embedder = make_embedder(settings)
    store = LanceSearchStore(settings.search_db, dim=embedder.dim, vector_weight=settings.vector_weight)
    searcher = Searcher(store, embedder, make_reranker(settings), candidates=settings.search_candidates)
    filters = SearchFilter(
        status=status, doc_type=doc_type or None,
        in_force_on=date.fromisoformat(in_force_on) if in_force_on else None,
    )
    for hit in searcher.search(query, filters=filters, k=k):
        c = hit.chunk
        version = f" v{c.version}" if c.version else ""
        typer.echo(f"{hit.score:7.3f}  {c.chunk_id}  {c.title}{version} [{c.status}]  {c.location}")


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


@graph_app.command("build")
def graph_build() -> None:
    """Rebuild the entity spine (Neptune bulk-load CSVs) from PLG Records."""
    settings = Settings.from_env()
    spine = settings.graph_dir / "spine"
    build = write_spine(settings.records_db, spine)
    typer.echo(f"Wrote {len(build.data.nodes)} nodes and {len(build.data.edges)} edges to {spine}")
    for problem in build.skipped:
        typer.echo(f"Skipped: {problem}", err=True)


@graph_app.command("show")
def graph_show(entity: str, hops: int = 2) -> None:
    """Resolve a name, unit number or ID and print what surrounds the best match."""
    graph = open_graph(Settings.from_env())
    matches = graph.resolve_entities(entity)
    if not matches:
        typer.echo("No entity matches.")
        raise typer.Exit(1)
    for m in matches:
        typer.echo(f"{m.id} | {m.label} | {m.name}")
    context = graph.entity_context(matches[0].id, hops)
    if context:
        typer.echo(f"\n{context.root.label} {context.root.id}: {len(context.nodes)} related, {len(context.edges)} links")
        for edge in context.edges:
            typer.echo(f"  {edge.start} -{edge.type}-> {edge.end}")


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
