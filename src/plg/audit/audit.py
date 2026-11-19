"""`plg audit`: the corpus audit report (issue #30).

Deterministic candidates (`candidates.py`) → Opus judgements (`judge.py`, a few in parallel; nothing unverified kept)
→ `CONFLICTS_WITH` / `DUPLICATE_OF` edges between `LibraryDocument` nodes via `GraphWriter` (validated as a whole,
append-only, so a re-run adds nothing new) → PLG Records rule checks (`rules.py`) → gaps from the question and
feedback logs (`gaps.py`) → the report, saved beside the earlier ones.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from plg.audit import judge
from plg.audit.candidates import Candidates, Corpus, StaleCandidate, Thresholds, candidates
from plg.audit.gaps import find_gaps
from plg.audit.model import AuditReport, Conflict, DocRef, StaleDocument, report_path, save_report
from plg.audit.questions import QuestionLog
from plg.audit.rules import check_rules
from plg.config import Settings
from plg.entities.model import Edge, Node
from plg.entities.writer import GraphWriter
from plg.feedback.model import FeedbackLog
from plg.llm import LLMClient
from plg.ontology.glossary import Glossary
from plg.ontology.vocab import VocabIndex
from plg.search.store import SearchStore

logger = logging.getLogger(__name__)
T = TypeVar("T")


def thresholds_for(settings: Settings) -> Thresholds:
    return Thresholds(duplicate_jaccard=settings.audit_duplicate_jaccard, max_pairs=settings.audit_max_pairs)


async def run_audit(
    store: SearchStore,
    llm: LLMClient,
    writer: GraphWriter,
    settings: Settings,
    *,
    vocab: VocabIndex,
    glossary: Glossary,
    now: datetime,
    mask: Callable[[str], str] = lambda text: text,
) -> AuditReport:
    """Audit the indexed corpus, write the graph edges and save the report (`settings.audit_reports_dir`). `glossary`
    is the live one (approved changes included); `mask` scrubs tenant PII from what Opus wrote."""
    corpus = Corpus.of(store)
    found = candidates(corpus, settings.records_db, glossary, thresholds_for(settings))
    report = AuditReport(generated_at=now, documents=len(corpus.documents))
    await _judge(llm, corpus, found, glossary, report, mask, settings.audit_concurrency)
    report.stale = [_stale(item) for item in found.stale]
    _write_graph(writer, report, corpus)
    report.rule_violations = check_rules(settings.records_db, vocab, corpus.documents)
    report.gaps = find_gaps(
        QuestionLog(settings.question_log).entries(), FeedbackLog(settings.feedback_log).entries(),
        settings.gap_min_score,
    )
    save_report(settings.audit_reports_dir, report)
    return report


async def _judge(
    llm: LLMClient, corpus: Corpus, found: Candidates, glossary: Glossary, report: AuditReport,
    mask: Callable[[str], str], concurrency: int,
) -> None:
    gate = asyncio.Semaphore(max(1, concurrency))

    async def gated(label: str, call: Awaitable[T]) -> T | None:
        async with gate:
            try:
                return await call
            except Exception as exc:  # one failed judgement must not lose the rest of the audit
                logger.warning("Audit judgement failed: %s", label, exc_info=True)
                report.dropped.append(f"{label}: the judgement failed ({type(exc).__name__})")
                return None

    duplicates = asyncio.gather(*(
        gated(judge.duplicate_request(d), judge.judge_duplicate(
            llm, d, corpus.chunks[d.a.doc_id], corpus.chunks[d.b.doc_id], mask))
        for d in found.duplicates
    ))
    pairs = asyncio.gather(*(gated(judge.pair_request(p), judge.judge_pair(llm, p, mask)) for p in found.conflicts))
    definitions = asyncio.gather(*(
        gated(judge.definition_request(d), judge.judge_definition(llm, d, glossary, mask)) for d in found.definitions
    ))
    dup_verdicts, pair_verdicts, definition_verdicts = await asyncio.gather(duplicates, pairs, definitions)

    seen: set[str] = set()
    for verdict in [*dup_verdicts, *pair_verdicts]:
        if verdict is None:
            continue
        report.dropped += verdict.dropped
        if verdict.duplicate:
            report.duplicates.append(verdict.duplicate)
        for conflict in verdict.conflicts:
            if conflict.id not in seen:
                seen.add(conflict.id)
                report.conflicts.append(conflict)
    for found_definitions in definition_verdicts:
        if found_definitions is not None:
            report.dropped += found_definitions.dropped
            report.superseded_definitions += found_definitions.findings


def _stale(item: StaleCandidate) -> StaleDocument:
    on = item.doc.effective_from
    relies_on = (
        f"{item.policy_id} v{item.relies_on.version}, the version in force on {on}" if item.relies_on and on
        else f"{item.policy_id} as it stood before {item.current.effective_from}"
    )
    return StaleDocument(
        doc=DocRef.of(item.doc), policy_id=item.policy_id, quote=item.quote, relies_on=relies_on,
        current_version=f"{item.policy_id} v{item.current.version}", current_from=item.current.effective_from,
        reason=(
            f"{item.doc.title} took effect on {on} and implements {item.policy_id}, whose current version "
            f"v{item.current.version} took effect later, on {item.current.effective_from}; it has not been revised since."
        ),
    )


def _write_graph(writer: GraphWriter, report: AuditReport, corpus: Corpus) -> None:
    """`DUPLICATE_OF` from each copy to its original and `CONFLICTS_WITH` from the source that doesn't prevail to the
    one that does (a → b when neither does), between `LibraryDocument` nodes (added if `plg categorise` hasn't)."""
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}

    def node(ref: DocRef) -> None:
        nodes.setdefault(ref.doc_id, Node(id=ref.doc_id, label="LibraryDocument", name=ref.title,
                                          props={"doc_type": ref.doc_type}))

    for dup in report.duplicates:
        node(dup.a)
        node(dup.b)
        edge = Edge(type="DUPLICATE_OF", start=dup.b.doc_id, end=dup.a.doc_id,
                    props={"similarity": dup.similarity, "kind": dup.kind})
        edges.setdefault(edge.id, edge)
    for conflict in report.conflicts:
        found = _conflict_edge(conflict)
        if found is None:
            continue
        for side in (conflict.a, conflict.b):
            node(DocRef.of(corpus.doc(side.doc_id or "")))
        edges.setdefault(found.id, found)
    fresh = [n for n in nodes.values() if writer.store.node(n.id) is None]
    writer.write(fresh, list(edges.values()))


def _conflict_edge(conflict: Conflict) -> Edge | None:
    if conflict.a.doc_id is None or conflict.b.doc_id is None:
        return None  # a PLG Records side is not a LibraryDocument
    start, end = (conflict.b, conflict.a) if conflict.prevails == "a" else (conflict.a, conflict.b)
    assert start.doc_id and end.doc_id
    return Edge(type="CONFLICTS_WITH", start=start.doc_id, end=end.doc_id, props={
        "conflict_id": conflict.id, "topic": conflict.topic, "evidence_chunk_id": start.chunk_id or "",
        "evidence_quote": start.quote,
    })


def report_location(settings: Settings, report: AuditReport) -> Path:
    """Where `run_audit` saved the report."""
    return report_path(settings.audit_reports_dir, report)
