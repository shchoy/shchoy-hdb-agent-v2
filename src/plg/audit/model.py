"""The corpus audit report (issue #30): what `plg audit` found, as saved and as `GET /audit/reports/latest` serves it."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from plg.search.models import DocStatus, DocumentMeta

FoundBy = Literal["similarity", "lineage", "records"]
DuplicateKind = Literal["near_duplicate", "same_content", "earlier_version"]
Rule = Literal["overlapping_tenancies", "two_current_policy_versions", "trade_not_allowed", "duplicate_tenants"]
GapReason = Literal["not_covered", "low_score", "thumbs_down"]


class DocRef(BaseModel):
    """A document as the report names it."""

    doc_id: str
    title: str
    doc_type: str
    version: str | None = None
    status: DocStatus = "current"

    @classmethod
    def of(cls, doc: DocumentMeta) -> DocRef:
        return cls(doc_id=doc.doc_id, title=doc.title, doc_type=doc.doc_type, version=doc.version, status=doc.status)


class Side(BaseModel):
    """One side of a conflict, cited: a span of a document chunk, or of a PLG Records row (`doc_id` None,
    `chunk_id` `record:<id>`)."""

    doc_id: str | None
    title: str
    chunk_id: str | None
    location: str | None = None
    version: str | None = None
    quote: str


class Conflict(BaseModel):
    id: str
    """A hash of the two sides' documents (or record) and the topic: stable across runs."""
    topic: str
    a: Side
    b: Side
    resolution: str
    """The expected resolution: which source prevails and why, in one or two sentences."""
    prevails: Literal["a", "b"] | None = None
    found_by: list[FoundBy]


class Duplicate(BaseModel):
    a: DocRef
    """The original (or earlier version)."""
    b: DocRef
    """The copy (or later version)."""
    similarity: float
    """Estimated Jaccard similarity of the two documents' word shingles (MinHash)."""
    kind: DuplicateKind
    note: str


class StaleDocument(BaseModel):
    """A document implementing a policy version that has since been superseded."""

    doc: DocRef
    policy_id: str
    quote: str
    """Where it names the policy."""
    relies_on: str
    """What it implements, e.g. the policy version in force on its own effective date."""
    current_version: str
    current_from: date | None
    reason: str


class SupersededDefinition(BaseModel):
    """A figure in a report that counts by a business definition no longer in force."""

    doc: DocRef
    chunk_id: str
    location: str
    quote: str
    concept: str
    used_version: str
    """Glossary term ID of the version the figure uses, e.g. plg:Vacant_v1."""
    current_version: str
    current_from: date | None
    explanation: str


class RuleViolation(BaseModel):
    rule: Rule
    entity_ids: list[str]
    detail: str


class Gap(BaseModel):
    """A question the corpus answers badly: not covered, weakly matched, or marked unhelpful."""

    question: str
    asked: int
    last_asked: datetime
    reasons: list[GapReason]
    top_score: float | None = None
    """The best retrieval score any asking got (None if none searched)."""


class AuditReport(BaseModel):
    generated_at: datetime
    documents: int
    """Documents audited (every indexed document, superseded versions too)."""
    conflicts: list[Conflict] = Field(default_factory=list)
    duplicates: list[Duplicate] = Field(default_factory=list)
    stale: list[StaleDocument] = Field(default_factory=list)
    superseded_definitions: list[SupersededDefinition] = Field(default_factory=list)
    rule_violations: list[RuleViolation] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    """Judgements that failed validation (a quote not verbatim in the named chunk, a chunk not shown) or a call that
    failed, with the reason: they are left out of the report."""


def report_path(directory: Path, report: AuditReport) -> Path:
    return directory / f"{report.generated_at.strftime('%Y%m%dT%H%M%S%f')}.json"


def save_report(directory: Path, report: AuditReport) -> Path:
    """Saved as `<timestamp>.json`, written atomically; earlier reports are kept."""
    directory.mkdir(parents=True, exist_ok=True)
    path = report_path(directory, report)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(report.model_dump_json(indent=2))
    os.replace(tmp, path)
    return path


def latest_report(directory: Path) -> AuditReport | None:
    """The newest saved report, or None if `plg audit` has never run."""
    saved = sorted(directory.glob("*.json")) if directory.is_dir() else []
    return AuditReport.model_validate_json(saved[-1].read_text()) if saved else None
