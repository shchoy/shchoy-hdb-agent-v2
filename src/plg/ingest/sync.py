"""`plg sync`: incremental ingestion of the text-bearing corpus into the `SearchStore`, by content hash.

Unchanged documents are not re-read or re-embedded. Superseded versions are marked, never deleted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from plg.ingest.chunking import location, sections, split
from plg.ingest.extract import ParsedDoc, ScanSource, extract
from plg.ingest.metadata import EntityTagger, control_meta, doc_type_for, lifecycle
from plg.ingest.scans import ScanError
from plg.ingest.sources import DocumentSource, Skipped, SourceDocument
from plg.ontology.vocab import load_vocab
from plg.search.embed import Embedder
from plg.search.models import Chunk, EntityRecord
from plg.search.store import SearchStore


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    """Documents newly marked superseded by this run."""
    chunks_written: int = 0


def sync(
    store: SearchStore,
    embedder: Embedder,
    sources: Sequence[DocumentSource],
    entities: Sequence[EntityRecord],
    tagger: EntityTagger,
    scans: ScanSource | None = None,
) -> SyncReport:
    report = SyncReport()
    indexed = {d.doc_id: d.content_hash for d in store.documents()}
    for source in sources:
        for item in source.documents():
            if isinstance(item, Skipped):
                report.skipped.append(item)
                continue
            content_hash = hashlib.sha256(item.path.read_bytes()).hexdigest()
            if indexed.get(item.doc_id) == content_hash:
                report.unchanged.append(item.rel_path)
                continue
            try:
                parsed = extract(item.path, scans)
            except ScanError as exc:  # a scan Claude could not read: report it, retry on the next sync
                report.skipped.append(Skipped(item.rel_path, f"scan could not be read: {exc}"))
                continue
            chunks = _chunks(item, parsed, content_hash, embedder, tagger)
            if not chunks:
                report.skipped.append(Skipped(item.rel_path, "no text layer (image-only scan)"))
                continue
            store.replace_document(item.doc_id, chunks)
            (report.updated if item.doc_id in indexed else report.added).append(item.rel_path)
            report.chunks_written += len(chunks)

    documents = store.documents()
    for doc_id, (status, effective_to) in lifecycle(documents).items():
        doc = next(d for d in documents if d.doc_id == doc_id)
        if (doc.status, doc.effective_to) != (status, effective_to):
            store.set_lifecycle(doc_id, status=status, effective_to=effective_to)
            if status == "superseded":
                report.superseded.append(doc.source_path)

    store.replace_entities(entities)
    optimize = getattr(store, "optimize", None)
    if callable(optimize):
        optimize()
    return report


def _chunks(
    doc: SourceDocument, parsed: ParsedDoc, content_hash: str, embedder: Embedder, tagger: EntityTagger
) -> list[Chunk]:
    doc_type = doc_type_for(doc.rel_path)
    control = control_meta(parsed.fields, doc.rel_path)
    title = doc.title or parsed.title or doc.path.stem
    doc_fields: dict[str, Any] = {
        "doc_id": doc.doc_id, "doc_type": doc_type, "title": title, "source_system": doc.source_system,
        "source_path": doc.rel_path, "policy_id": control.policy_id, "version": control.version,
        "effective_from": control.effective_from, "effective_to": control.effective_to,
        "content_hash": content_hash,
    }
    context = [title, f"Type: {_doc_type_label(doc_type)}"]
    if control.policy_id:
        context.append(f"{control.policy_id} v{control.version}" if control.version else control.policy_id)
    if control.effective_from:
        period = f"Effective from {control.effective_from.isoformat()}"
        context.append(f"{period} to {control.effective_to.isoformat()}" if control.effective_to else period)

    pending: list[dict[str, Any]] = []
    for section in sections(parsed.blocks):
        pieces = split(section.text)
        for part, text in enumerate(pieces):
            where = location(section, part, len(pieces))
            header = " | ".join([*context, f"Section: {where}"])
            tags = tagger.tag(f"{title}\n{' '.join(section.path)}\n{text}")
            entity_ids = list(dict.fromkeys([*([control.policy_id] if control.policy_id else []), *tags.entity_ids]))
            seq = len(pending)
            pending.append({
                **doc_fields, "chunk_id": f"{doc.doc_id}#{seq:03d}", "seq": seq, "header": header,
                "text": text, "location": where, "town": tags.town, "nc": tags.nc, "trade": tags.trade,
                "entity_ids": entity_ids,
            })
    vectors = embedder.embed_documents([f"{c['header']}\n{c['text']}" for c in pending])
    return [Chunk(**c, vector=v) for c, v in zip(pending, vectors, strict=True)]


def _doc_type_label(notation: str) -> str:
    labels = {c.notation: c.pref_label for c in load_vocab().scheme("plg:document_types")}
    return labels.get(notation, notation)
