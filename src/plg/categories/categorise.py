"""`plg categorise`: group the indexed documents into named categories.

Each document's vector is the normalised mean of its chunks' embeddings; HDBSCAN groups similar documents and leaves
outliers uncategorised. Haiku names every group in one forced `name_categories` call, from its titles and the opening
of its most central documents. The result goes three ways: the saved categorisation file (what the Library and the
`category_summary` specialist read), each chunk's `category` metadata, and `IN_CATEGORY` edges in the entity graph via
`GraphWriter`. A category's ID is a hash of its members; a group whose members are unchanged keeps its ID and name
(Haiku names only new groups), so re-running over an unchanged index changes nothing and calls no model.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN

from plg.categories.model import Categorisation, Category, CategoryDocument, save_categorisation
from plg.entities.model import Edge, Node
from plg.entities.writer import GraphWriter
from plg.agents.runtime import CACHE
from plg.llm import Block, LLMClient
from plg.search.models import DocumentMeta
from plg.search.store import SearchStore

NODE = "categorise"
TOOL = "name_categories"
MAX_TITLES = 20
EXCERPTS = 2
EXCERPT_CHARS = 400

SYSTEM = """\
You name groups of documents in the library of PLG (the Properties & Land Group, which lets commercial units in public \
housing estates). Each group was found by clustering the documents' embeddings, so its documents are about one thing. \
For every cluster give a short name an officer would browse by (2 to 5 words, PLG's own terms, e.g. "Rental arrears \
recovery"), one sentence describing what its documents are about, and a summary of 2 to 4 sentences of what they say, \
naming the key documents (policy or circular IDs where given). Use only what the titles and excerpts show."""

NAME_REQUEST = "Name each cluster of PLG documents below."
"""The user message's opening text block (the listing follows in a second block)."""


def tool() -> Block:
    return {
        "name": TOOL,
        "description": "Record the name, description and summary of every cluster.",
        "input_schema": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cluster": {"type": "integer", "description": "The cluster's number in the listing."},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "summary": {"type": "string"},
                        },
                        "required": ["cluster", "name", "description", "summary"],
                    },
                },
            },
            "required": ["categories"],
        },
        "cache_control": CACHE,
    }


@dataclass
class CategoriseReport:
    categorisation: Categorisation
    changed: int
    """Documents whose category differs from the previous run's."""


def category_id(doc_ids: Sequence[str]) -> str:
    return "CAT-" + hashlib.sha1(",".join(sorted(doc_ids)).encode()).hexdigest()[:8]


def document_vectors(store: SearchStore) -> tuple[list[DocumentMeta], np.ndarray]:
    """Every indexed document (superseded versions too) with its unit-length mean chunk vector."""
    documents = store.documents()
    kept, rows = [], []
    for doc in documents:
        chunks = store.chunks(doc.doc_id)
        if not chunks:  # nothing to place it by
            continue
        mean = np.mean([c.vector for c in chunks], axis=0)
        kept.append(doc)
        rows.append(mean / (np.linalg.norm(mean) or 1.0))
    return kept, np.array(rows)


def cluster(vectors: np.ndarray, min_size: int) -> list[int]:
    """A cluster number per row; -1 for an outlier. Fewer documents than `min_size` form no cluster."""
    if len(vectors) < max(min_size, 2):
        return [-1] * len(vectors)
    labels = HDBSCAN(min_cluster_size=min_size, copy=True).fit_predict(vectors)
    return [int(label) for label in labels]


def listing(groups: Sequence[Sequence[DocumentMeta]], excerpts: Sequence[Sequence[str]]) -> str:
    parts = []
    for n, (docs, quotes) in enumerate(zip(groups, excerpts, strict=True), start=1):
        lines = [f"Cluster {n} ({len(docs)} documents)", "Documents:"]
        lines += [f"- {d.title} ({d.doc_type}, {d.status})" for d in docs[:MAX_TITLES]]
        if len(docs) > MAX_TITLES:
            lines.append(f"- ... and {len(docs) - MAX_TITLES} more")
        lines += ["Excerpts:", *(f"> {q}" for q in quotes)]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def name_groups(
    llm: LLMClient, groups: Sequence[Sequence[DocumentMeta]], excerpts: Sequence[Sequence[str]]
) -> list[tuple[str, str, str]]:
    """(name, description, summary) per group, in order. A group Haiku left out is named after its first title."""
    if not groups:
        return []
    reply = await llm.complete(
        node=NODE, tier="haiku", system=[{"type": "text", "text": SYSTEM, "cache_control": CACHE}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": NAME_REQUEST}, {"type": "text", "text": listing(groups, excerpts)},
        ]}],
        tools=[tool()], tool_choice={"type": "tool", "name": TOOL},
    )
    call = next((b for b in reply.content if b["type"] == "tool_use"), None)
    named = {}
    for given in call["input"].get("categories", []) if call else []:
        if isinstance(given, dict) and isinstance(given.get("cluster"), int):
            named[given["cluster"]] = given
    out = []
    for n, docs in enumerate(groups, start=1):
        given = named.get(n, {})
        out.append((
            str(given.get("name") or "").strip() or f"Documents like {docs[0].title}",
            str(given.get("description") or "").strip(),
            str(given.get("summary") or "").strip(),
        ))
    return out


async def categorise(
    store: SearchStore,
    llm: LLMClient,
    writer: GraphWriter,
    path: Path,
    *,
    min_size: int,
    previous: Categorisation,
    now: datetime,
    mask: Callable[[str], str] = lambda text: text,
) -> CategoriseReport:
    """`mask` scrubs tenant PII from what Haiku wrote (it read excerpts) before it is saved and shown to every user."""
    documents, vectors = document_vectors(store)
    labels = cluster(vectors, min_size)
    members: dict[int, list[int]] = {}
    for row, label in enumerate(labels):
        if label >= 0:
            members.setdefault(label, []).append(row)
    ordered = sorted(members.values(), key=lambda rows: (-len(rows), documents[rows[0]].title))
    groups = [[documents[r] for r in rows] for rows in ordered]
    ids = [category_id([d.doc_id for d in docs]) for docs in groups]
    known = {c.id: c for c in previous.categories}
    # A group with the same members as last time keeps its name, so names are stable and Haiku names only new groups.
    fresh = [n for n, cid in enumerate(ids) if cid not in known]
    named = await name_groups(
        llm, [groups[n] for n in fresh], [_excerpts(store, documents, vectors, ordered[n]) for n in fresh]
    )
    names = {n: (mask(a), mask(b), mask(c)) for n, (a, b, c) in zip(fresh, named, strict=True)}
    for n, cid in enumerate(ids):
        if cid in known:
            names[n] = (known[cid].name, known[cid].description, known[cid].summary)

    categories = [
        Category(
            id=cid, name=names[n][0], description=names[n][1], summary=names[n][2],
            documents=[CategoryDocument.of(d) for d in groups[n]],
        )
        for n, cid in enumerate(ids)
    ]
    of = {d.doc_id: c.id for c in categories for d in c.documents}
    before = {d.doc_id: c.id for c in previous.categories for d in c.documents}
    _write_graph(writer, categories)  # first: it validates everything, so a refusal leaves chunks and file as they were
    for doc in store.documents():
        if doc.category != of.get(doc.doc_id):
            store.set_category(doc.doc_id, of.get(doc.doc_id))

    result = Categorisation(
        categorised_at=now, categories=categories,
        uncategorised=[CategoryDocument.of(d) for d in documents if d.doc_id not in of],
    )
    save_categorisation(path, result)
    changed = sum(1 for d in documents if before.get(d.doc_id) != of.get(d.doc_id))
    return CategoriseReport(result, changed)


def _excerpts(store: SearchStore, documents: list[DocumentMeta], vectors: np.ndarray, rows: list[int]) -> list[str]:
    """The opening of the documents nearest the group's centre."""
    centre = vectors[rows].mean(axis=0)
    nearest = sorted(rows, key=lambda r: -float(vectors[r] @ centre))[:EXCERPTS]
    out = []
    for r in nearest:
        chunks = store.chunks(documents[r].doc_id)
        if chunks:
            out.append(" ".join(chunks[0].text.split())[:EXCERPT_CHARS])
    return out


def _write_graph(writer: GraphWriter, categories: list[Category]) -> None:
    """A `DocumentCategory` node per category and an `IN_CATEGORY` edge from each member's `LibraryDocument` node.
    The graph is append-only: nodes and edges already there are left as they are."""
    nodes: list[Node] = []
    edges: list[Edge] = []
    for category in categories:
        nodes.append(Node(
            id=category.id, label="DocumentCategory", name=category.name, props={"definition": category.description},
        ))
        for doc in category.documents:
            nodes.append(Node(id=doc.doc_id, label="LibraryDocument", name=doc.title, props={"doc_type": doc.doc_type}))
            edges.append(Edge(type="IN_CATEGORY", start=doc.doc_id, end=category.id))
    fresh = [n for n in {n.id: n for n in nodes}.values() if writer.store.node(n.id) is None]
    writer.write(fresh, edges)
