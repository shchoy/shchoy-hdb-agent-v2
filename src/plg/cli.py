"""`plg` CLI. Drives the same graph as plg-api."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from datetime import date
from typing import Annotated, Any

import typer
from dotenv import find_dotenv, load_dotenv

from plg.config import Settings
from plg.entities.open import LazyGraph, open_graph
from plg.entities.spine import write_spine
from plg.events import CitationEvent, ErrorEvent, TokenEvent
from plg.data.warehouse import Warehouse
from plg.graph.build import build_graph
from plg.identity import UserCtx, load_personas
from plg.memory.store import MemoryStore, view
from plg.llm import AnthropicLLMClient, LLMClient, ScriptedLLMClient
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.changes import GlossaryChanges
from plg.ontology.glossary import Glossary, load_glossary
from plg.runs import stream_run
from plg.tasks.rules import DEFAULT_LIMIT as DEFAULT_TASKS
from plg.search.embed import Embedder, VoyageEmbedder
from plg.search.models import DocStatus, SearchFilter
from plg.search.rerank import LazySearcher, Reranker, Retriever
from plg.search.store import SearchStore
from plg.search.rerank import make_reranker as build_reranker
from plg.tracing import Tracer, install_tracer

app = typer.Typer(help="PLG Super-Librarian", no_args_is_help=True)
graph_app = typer.Typer(help="Entity graph built from PLG Records.", no_args_is_help=True)
app.add_typer(graph_app, name="graph")
glossary_app = typer.Typer(help="Business glossary: versioned definitions.", no_args_is_help=True)
app.add_typer(glossary_app, name="glossary")
memory_app = typer.Typer(help="An officer's personal long-term memory.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
eval_app = typer.Typer(help="Golden datasets and quality evaluations (LangSmith).", no_args_is_help=True)
app.add_typer(eval_app, name="eval")


def make_llm(settings: Settings) -> LLMClient:
    return AnthropicLLMClient(settings)


def make_tracer(settings: Settings) -> Tracer | None:
    """LangSmith tracing with tenant PII masked, when configured; also the default for Claude calls outside a run."""
    return install_tracer(settings)


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
    graph = build_graph(make_llm(settings), LazySearcher(settings), entities=LazyGraph(settings), warehouse=Warehouse(settings.records_db, settings.trackers_db))
    tracer = make_tracer(settings)

    async def run() -> bool:
        citations: list[CitationEvent] = []
        async for event in stream_run(graph, str(uuid.uuid4()), question, tracer=tracer, channel="cli"):
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
    full: bool = typer.Option(
        False, "--full", help="Re-read and re-embed every document (in place: history and memories are kept)."
    ),
) -> None:
    """Ingest changed corpus documents (SharePoint and Lotus Notes mocks) into the search index, and load the Excel
    trackers into DuckDB for data questions. Safe to schedule: one run at a time per index; exits 1 if another run
    holds the index or any document could not be read (the rest are still ingested)."""
    from plg.data.trackers import load_trackers
    from plg.ingest.metadata import load_entity_spine
    from plg.ingest.scans import ScanReader, TranscriptStore
    from plg.ingest.sources import DocumentSource, LotusNotesSource, SharePointSource
    from plg.ingest.sync import SyncRunning, sync_lock
    from plg.ingest.sync import sync as run_sync
    from plg.search.lance import LanceSearchStore

    settings = Settings.from_env()
    embedder = make_embedder(settings)
    try:
        with sync_lock(settings.search_db):
            store = LanceSearchStore(settings.search_db, dim=embedder.dim, vector_weight=settings.vector_weight)
            entities, tagger = load_entity_spine(settings.records_db)
            sources: list[DocumentSource] = [
                SharePointSource(settings.corpus_dir), LotusNotesSource(settings.corpus_dir)
            ]
            make_tracer(settings)  # scan transcription is traced (PII masked) when LangSmith is configured
            scans = ScanReader(make_llm(settings), TranscriptStore(settings.transcripts_dir))
            report = run_sync(store, embedder, sources, entities, tagger, scans, full=full)
            workbooks = load_trackers(settings.corpus_dir, settings.trackers_db)
    except SyncRunning as exc:
        typer.echo(f"{exc}; not starting another.", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(
        f"Added {len(report.added)}, updated {len(report.updated)}, unchanged {len(report.unchanged)}, "
        f"skipped {len(report.skipped)}, failed {len(report.failed)} documents; wrote {report.chunks_written} chunks."
    )
    for path in report.superseded:
        typer.echo(f"Superseded: {path}")
    for path in report.flagged:
        typer.echo(f"Flagged: {path} (suspected prompt injection; instructions removed)")
    for path in report.missing:
        typer.echo(f"No longer available from its source (kept): {path}")
    for skipped in report.skipped:
        typer.echo(f"Skipped: {skipped.rel_path} ({skipped.reason})")
    for failed in report.failed:
        typer.echo(f"Failed: {failed.rel_path} ({failed.reason})")

    tables = [t for wb in workbooks for t in wb.tables]
    typer.echo(
        f"Loaded {len(workbooks)} trackers into {len(tables)} tables ({sum(t.rows for t in tables)} rows); "
        f"restart plg-api to query them."
    )
    if report.failed:
        raise typer.Exit(code=1)


@app.command()
def categorise() -> None:
    """Group the indexed documents into named categories for the Library: HDBSCAN over their embeddings, each group
    named and summarised by Haiku. Writes the categories file, each chunk's category and IN_CATEGORY graph edges. Run
    after `plg sync` (it takes the same index lock); a re-run over an unchanged index changes nothing."""
    from datetime import UTC, datetime

    from plg.categories.categorise import categorise as run_categorise
    from plg.categories.model import load_categorisation
    from plg.entities.writer import GraphWriter
    from plg.ingest.sync import SyncRunning, sync_lock
    from plg.search.lance import LanceSearchStore
    from plg.tracing import pii_masker

    settings = Settings.from_env()
    try:
        with sync_lock(settings.search_db):
            store = LanceSearchStore(settings.search_db, dim=settings.embed_dim, vector_weight=settings.vector_weight)
            if not store.documents():
                typer.echo("Nothing is indexed yet: run `plg sync` first.", err=True)
                raise typer.Exit(code=1)
            make_tracer(settings)  # the naming call is traced (PII masked) when LangSmith is configured
            report = asyncio.run(run_categorise(
                store, make_llm(settings), GraphWriter(settings.graph_dir, open_graph(settings)),
                settings.categories_file, min_size=settings.category_min_size,
                previous=load_categorisation(settings.categories_file), now=datetime.now(UTC),
                mask=pii_masker(settings.records_db),
            ))
    except SyncRunning as exc:
        typer.echo(f"{exc}; try again when it finishes.", err=True)
        raise typer.Exit(code=1) from None

    result = report.categorisation
    placed = sum(len(c.documents) for c in result.categories)
    typer.echo(
        f"Categorised {placed} documents into {len(result.categories)} categories "
        f"({len(result.uncategorised)} uncategorised, {report.changed} changed category)."
    )
    for category in result.categories:
        typer.echo(f"{category.id}  {category.name} ({len(category.documents)})")


@app.command()
def audit() -> None:
    """Audit the indexed corpus for a policy owner: conflicting documents (both sides cited, with the expected
    resolution), near-duplicates, stale SOPs, report figures using superseded definitions, PLG Records rule
    violations and gaps (questions answered badly). Candidates are found deterministically and judged by Opus;
    CONFLICTS_WITH / DUPLICATE_OF edges go into the entity graph. Run after `plg sync` (it takes the same index lock).
    The report is saved under the audit reports directory and served at GET /audit/reports/latest."""
    from datetime import UTC, datetime

    from plg.audit.audit import report_location, run_audit
    from plg.entities.writer import GraphWriter
    from plg.ingest.sync import SyncRunning, sync_lock
    from plg.ontology.vocab import load_vocab
    from plg.search.lance import LanceSearchStore
    from plg.tracing import pii_masker

    settings = Settings.from_env()
    try:
        with sync_lock(settings.search_db):
            store = LanceSearchStore(settings.search_db, dim=settings.embed_dim, vector_weight=settings.vector_weight)
            if not store.documents():
                typer.echo("Nothing is indexed yet: run `plg sync` first.", err=True)
                raise typer.Exit(code=1)
            make_tracer(settings)  # the Opus judgements are traced (PII masked) when LangSmith is configured
            report = asyncio.run(run_audit(
                store, make_llm(settings), GraphWriter(settings.graph_dir, open_graph(settings)), settings,
                vocab=load_vocab(), glossary=GlossaryChanges(settings.glossary_changes).glossary(load_glossary()),
                now=datetime.now(UTC), mask=pii_masker(settings.records_db),
            ))
    except SyncRunning as exc:
        typer.echo(f"{exc}; try again when it finishes.", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Audited {report.documents} documents.")
    typer.echo(f"Conflicts: {len(report.conflicts)}")
    for c in report.conflicts:
        typer.echo(f"  {c.id}  {c.topic}: {c.a.title} / {c.b.title}")
    typer.echo(f"Duplicates: {len(report.duplicates)}")
    for d in report.duplicates:
        typer.echo(f"  {d.b.title} duplicates {d.a.title} ({d.kind}, similarity {d.similarity:.2f})")
    typer.echo(f"Stale documents: {len(report.stale)}")
    for s in report.stale:
        typer.echo(f"  {s.doc.title}: implements {s.relies_on}; current is {s.current_version}")
    typer.echo(f"Superseded definitions: {len(report.superseded_definitions)}")
    for u in report.superseded_definitions:
        typer.echo(f"  {u.doc.title} ({u.location}): uses {u.used_version}, current is {u.current_version}")
    typer.echo(f"Rule violations: {len(report.rule_violations)}")
    for v in report.rule_violations:
        typer.echo(f"  {v.rule}: {v.detail}")
    typer.echo(f"Gaps: {len(report.gaps)}")
    if report.dropped:
        typer.echo(f"Dropped judgements: {len(report.dropped)} (unverified quotes or failed calls; see the report)")
    typer.echo(f"Report: {report_location(settings, report)}")


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


@app.command()
def digest(
    user: Annotated[
        str | None, typer.Option("--user", "-u", help="Staff ID, e.g. S12. Default: every officer with open tasks.")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, help="Tasks per officer.")] = DEFAULT_TASKS,
    out: Annotated[Path | None, typer.Option(help="Write the digest to this file instead of the console.")] = None,
) -> None:
    """Task digest: officers' top open tasks ranked by urgency × impact, overdue ones marked. For scheduled runs."""
    from plg.tasks import rules

    settings = Settings.from_env()
    personas = load_personas(settings.records_db)
    if user is not None and user not in personas:
        typer.echo(f"Unknown staff ID {user}.", err=True)
        raise typer.Exit(code=1)
    officers = [personas[user]] if user else list(personas.values())
    digests = [rules.digest(settings.records_db, o, settings.tasks_today, limit) for o in officers]
    text = "\n\n".join(rules.render(d) for d in digests if d.open_count or user)
    if out is None:
        typer.echo(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    typer.echo(f"Task digest written to {out}.")


@graph_app.command("build")
def graph_build() -> None:
    """Rebuild the entity spine (Neptune bulk-load CSVs) from PLG Records."""
    settings = Settings.from_env()
    spine = settings.graph_dir / "spine"
    build = write_spine(settings.records_db, spine)
    typer.echo(f"Wrote {len(build.data.nodes)} nodes and {len(build.data.edges)} edges to {spine}")
    for problem in build.skipped:
        typer.echo(f"Skipped: {problem}", err=True)


@graph_app.command("lineage")
def graph_lineage() -> None:
    """Have Haiku extract SUPERSEDES / OVERRIDES / APPLIES edges from the indexed corpus into the graph."""
    from plg.entities.writer import GraphWriter
    from plg.ingest.lineage import extract_lineage
    from plg.search.lance import LanceSearchStore

    settings = Settings.from_env()
    embedder = make_embedder(settings)
    store = LanceSearchStore(settings.search_db, dim=embedder.dim, vector_weight=settings.vector_weight)
    graph = open_graph(settings)
    make_tracer(settings)  # lineage extraction is traced (PII masked) when LangSmith is configured
    report = asyncio.run(extract_lineage(make_llm(settings), store, GraphWriter(settings.graph_dir, graph)))
    typer.echo(f"Wrote {report.nodes} nodes and {report.edges} edges to {settings.graph_dir / 'delta'}")
    for problem in report.dropped:
        typer.echo(f"Dropped: {problem}", err=True)


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


def _glossary() -> Glossary:
    """The generated glossary with the changes approved since (PLG_GLOSSARY_CHANGES)."""
    return GlossaryChanges(Settings.from_env().glossary_changes).glossary(load_glossary())


@glossary_app.command("list")
def glossary_list(
    all_versions: bool = typer.Option(False, "--all", help="Also list superseded and proposed versions."),
) -> None:
    """List glossary terms at their current version."""
    glossary = _glossary()
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
    glossary = _glossary()
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


def make_memory(settings: Settings) -> MemoryStore:
    from plg.search.embed import LazyEmbedder
    from plg.search.lance import LanceSearchStore

    return MemoryStore(
        lambda: LanceSearchStore(settings.search_db, dim=settings.embed_dim, vector_weight=settings.vector_weight),
        LazyEmbedder(settings),
    )


def _memory_for(staff_id: str) -> tuple[MemoryStore, UserCtx]:
    settings = Settings.from_env()
    user = load_personas(settings.records_db).get(staff_id)
    if user is None:
        typer.echo(f"Unknown staff ID {staff_id}.", err=True)
        raise typer.Exit(code=1)
    return make_memory(settings), user


StaffOption = Annotated[str, typer.Option("--user", "-u", help="Staff ID whose memory this is, e.g. S05.")]


@memory_app.command("list")
def memory_list(user: StaffOption) -> None:
    """List what the assistant remembers about an officer, and where each note came from."""
    store, who = _memory_for(user)
    store.seed_profile(who)
    for item in store.items(who.staff_id):
        flag = " [flagged: conflicts with current policy]" if item.status == "pending_review" else ""
        typer.echo(f"{item.key}  ({item.namespace[2]}){flag}\n    {item.text}\n    from: {item.provenance}")


@memory_app.command("show")
def memory_show(memory_id: str, user: StaffOption) -> None:
    """Show one memory."""
    store, who = _memory_for(user)
    item = store.find(who.staff_id, memory_id)
    if item is None:
        typer.echo("Memory not found.", err=True)
        raise typer.Exit(code=1)
    typer.echo(view(item).model_dump_json(indent=2))


@memory_app.command("edit")
def memory_edit(memory_id: str, text: str, user: StaffOption) -> None:
    """Reword a memory."""
    store, who = _memory_for(user)
    if store.edit(who.staff_id, memory_id, text=text, status=None) is None:
        typer.echo("Memory not found.", err=True)
        raise typer.Exit(code=1)
    typer.echo("Updated.")


@memory_app.command("forget")
def memory_forget(memory_id: str, user: StaffOption) -> None:
    """Forget a memory."""
    store, who = _memory_for(user)
    if not store.forget(who.staff_id, memory_id):
        typer.echo("Memory not found.", err=True)
        raise typer.Exit(code=1)
    typer.echo("Forgotten.")


# ---------------------------------------------------------------- evals (#31)

def make_eval_client(settings: Settings) -> Any:
    """The LangSmith client datasets are seeded and experiments uploaded with (tenant PII masked)."""
    from plg.tracing import tracing_client

    if not os.environ.get("LANGSMITH_API_KEY"):
        typer.echo("LANGSMITH_API_KEY is not set. Add it to .env, or run with --offline.", err=True)
        raise typer.Exit(code=1)
    return tracing_client(settings.records_db)


def make_eval_index(settings: Settings, *, audit: bool) -> tuple[Retriever, SearchStore | None]:
    """The searcher the eval harness asks over (opened on first search) and, for the corpus audit, the `plg sync`
    index itself."""
    from plg.search.lance import LanceSearchStore

    store = LanceSearchStore(settings.search_db, dim=settings.embed_dim, vector_weight=settings.vector_weight) if audit else None
    return LazySearcher(settings), store


def _dataset_names(names: list[str]) -> list[str]:
    from plg.evals.golden import DATASETS

    unknown = [n for n in names if n not in DATASETS]
    if unknown:
        typer.echo(f"Unknown dataset(s) {', '.join(unknown)}: one of {', '.join(DATASETS)}.", err=True)
        raise typer.Exit(code=1)
    return names or list(DATASETS)


@eval_app.command("list")
def eval_list() -> None:
    """The golden datasets: examples, the regression gate's subset and the POC target."""
    from plg.evals.evaluators import TARGETS
    from plg.evals.golden import DATASETS, dataset

    for name in DATASETS:
        examples = dataset(name)
        target = TARGETS[name]
        typer.echo(f"{name:<11} {len(examples):>3} examples ({sum(e.gate for e in examples)} in the gate)  "
                   f"target {target.metric} >= {target.threshold:.0%}")


@eval_app.command("seed")
def eval_seed(names: Annotated[list[str] | None, typer.Argument(help="Datasets (default: all).")] = None) -> None:
    """Create or update the LangSmith datasets `plg-<name>` from the corpus ground truth (idempotent)."""
    from plg.evals.runner import seed

    settings = Settings.from_env()
    for result in seed(make_eval_client(settings), _dataset_names(names or [])):
        typer.echo(f"{result.dataset}: {result.created} created, {result.updated} updated, {result.removed} removed")


@eval_app.command("run")
def eval_run(
    names: Annotated[list[str] | None, typer.Argument(help="Datasets (default: all).")] = None,
    gate: bool = typer.Option(False, help="Only the regression gate's subset."),
    limit: int | None = typer.Option(None, help="At most this many examples per dataset."),
    offline: bool = typer.Option(False, help="Score locally; upload nothing to LangSmith."),
    label: str | None = typer.Option(None, help="Experiment label, e.g. the prompt or tier being compared."),
    model: list[str] = typer.Option([], help="Override a tier's model, e.g. sonnet=claude-haiku-5-5 (repeatable)."),
    concurrency: int = typer.Option(4, help="Examples run at once."),
) -> None:
    """Run golden datasets with real Claude and compare each with its POC target; exits 1 if any falls short."""
    from plg.evals.evaluators import Judge
    from plg.evals.harness import Harness
    from plg.evals.runner import run

    settings = Settings.from_env()
    for override in model:
        tier, _, model_id = override.partition("=")
        if tier not in ("haiku", "sonnet", "opus") or not model_id:
            typer.echo(f"--model takes tier=model_id (tier haiku, sonnet or opus), not {override!r}.", err=True)
            raise typer.Exit(code=1)
        settings = settings.model_copy(update={f"model_{tier}": model_id})
    selected = _dataset_names(names or [])
    client = None if offline else make_eval_client(settings)
    if client is not None:
        make_tracer(settings)  # the harness's runs are traced under the experiment
    llm = make_llm(settings)
    retriever, store = make_eval_index(settings, audit="audit" in selected)
    harness = Harness(llm, retriever, settings, entities=LazyGraph(settings))

    async def run_all() -> bool:
        passed = True
        for name in selected:
            report = await run(name, harness, Judge(llm), store=store, gate=gate, limit=limit, client=client,
                               label=label, concurrency=concurrency)
            score = report.score or 0.0
            verdict = "PASS" if report.passed else "FAIL"
            where = f"  experiment {report.experiment}" if report.experiment else ""
            typer.echo(f"{verdict} {name}: {report.target.metric} {score:.0%} (target {report.target.threshold:.0%}, "
                       f"{len(report.rows)} examples){where}")
            for key, value in sorted(report.scores.items()):
                if key != report.target.metric:
                    typer.echo(f"    {key} {value:.0%}")
            for row in report.rows:
                for m in row.metrics:
                    if m["score"] < 1 and m["key"] == report.target.metric:
                        typer.echo(f"    - {row.id}: {m['comment']}")
            passed = passed and report.passed
        return passed

    if not asyncio.run(run_all()):
        raise typer.Exit(code=1)
