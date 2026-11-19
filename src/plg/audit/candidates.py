"""Candidate generation for the corpus audit: deterministic, no Claude. Everything here is a *candidate* for Opus to
judge (see `judge.py`), except stale documents, which follow from the index metadata alone.

- Duplicates: MinHash signatures over word shingles, banded into LSH buckets, estimate each pair's Jaccard similarity;
  the documents' mean chunk vectors confirm borderline pairs. Two emails are never paired: a reply quotes the message
  it answers, which is a thread, not a duplicate.
- Conflicts by similarity: chunks of two current documents that state a quantity of the same kind (days, months,
  metres, S$, units, %) with different values among the same words ("security deposit ... two (2) months' rent" vs
  "... three (3) months' rent"). Compared pairs come from each chunk's nearest chunks by vector, and from an inverted
  index on (kind of quantity, word near it), so lexical clashes are found whatever the embeddings. Grouped by document
  pair, ranked by how alike the words around the clashing quantities are; superseded documents, a document's other
  versions and its copies (near-identical duplicates; their original stands for them) are left out.
- Lineage: a current SOP naming a policy (PLG-POL-nnn) that took effect before the policy's current version, where an
  earlier version was superseded, is stale; it is also paired with the current policy version for Opus to compare.
- Records: a rent sentence stating an S$ amount other than the PLG Records monthly rent of the one tenancy its chunk
  names is paired with that tenancy's record.
- Superseded definitions: report and deck chunks giving a figure next to a business term whose glossary definition
  changed (a superseded version exists), grouped per document.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from plg.audit.model import FoundBy
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.glossary import Glossary
from plg.search.models import Chunk, DocumentMeta
from plg.search.store import SearchStore

PERMUTATIONS = 128
BANDS = 32
SHINGLE = 3
_PRIME = (1 << 31) - 1
_SEED = 30


@dataclass(frozen=True)
class Thresholds:
    duplicate_jaccard: float = 0.5
    """Estimated Jaccard at which two documents are a duplicate candidate on MinHash alone."""
    duplicate_borderline: float = 0.3
    """Below `duplicate_jaccard`, a pair is still a candidate when its document vectors are this close..."""
    duplicate_cosine: float = 0.95
    """... (cosine of the documents' mean chunk vectors)."""
    copy_jaccard: float = 0.65
    """A document this close to another (and not another version of it) is taken as its copy: conflicts are looked
    for in the original only."""
    neighbours: int = 20
    """Nearest chunks of other documents looked at per chunk."""
    chunk_cosine: float = 0.2
    """The least cosine similarity of two chunks compared for conflicting quantities."""
    claim_overlap: float = 0.15
    """The least overlap of the words around two differing quantities for them to be about the same thing."""
    max_pairs: int = 40
    """Document pairs sent to Opus for a conflict judgement, at most (lineage and records pairs first)."""
    chunks_per_side: int = 4
    """Chunks of each document shown to Opus for one pair."""


# ---------------------------------------------------------------- the corpus


@dataclass
class Corpus:
    documents: list[DocumentMeta]
    chunks: dict[str, list[Chunk]]
    """Chunks per doc_id, in reading order."""

    @classmethod
    def of(cls, store: SearchStore) -> Corpus:
        documents = store.documents()
        chunks = {d.doc_id: store.chunks(d.doc_id) for d in documents}
        return cls([d for d in documents if chunks[d.doc_id]], chunks)

    def doc(self, doc_id: str) -> DocumentMeta:
        return next(d for d in self.documents if d.doc_id == doc_id)

    def text(self, doc_id: str) -> str:
        return "\n".join(c.text for c in self.chunks[doc_id])


# ---------------------------------------------------------------- quantities

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fourteen": 14, "thirty": 30, "forty-five": 45, "sixty": 60,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(_NUMBER_WORDS) + r")(?:\s*\(\d+\))?"
_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "days": [re.compile(rf"\b{_NUM}\s*(?:calendar\s+|working\s+|business\s+)?days?\b", re.I),
             re.compile(r"\bday\s+(\d+)\b", re.I)],
    "months": [re.compile(rf"\b{_NUM}\s*months?(?:'|\b)", re.I)],
    "metres": [re.compile(r"\b(\d+(?:\.\d+)?)\s?m\b(?![²2])", re.I)],
    "money": [re.compile(r"S\$\s?(\d[\d,]*(?:\.\d+)?)")],
    "units": [re.compile(r"\b(\d+)\s+(?:vacant\s+|tenanted\s+|commercial\s+)?units\b", re.I),
              re.compile(r"\bunits?:\s*(\d+)\b", re.I)],
    "percent": [re.compile(r"\b(\d+(?:\.\d+)?)\s?%")],
}


def _value(raw: str) -> float:
    word = raw.casefold()
    return float(_NUMBER_WORDS[word]) if word in _NUMBER_WORDS else float(raw.replace(",", ""))


CONTEXT_WORDS = 8
"""Words either side of a quantity that say what it is the quantity of."""
_STOP = frozenset(
    "the a an of to in is are and or for be by on at with any this that it as from up per not no its will shall may "
    "must can all our your you we they their there has have been was were which who also than then into".split()
)


@dataclass(frozen=True)
class Mention:
    """A quantity a text states, and the (crudely stemmed) words around it."""

    kind: str
    value: float
    context: frozenset[str]


def mentions(text: str) -> list[Mention]:
    squashed = " ".join(text.split())
    found = []
    for kind, patterns in _PATTERNS.items():
        for pattern in patterns:
            for m in pattern.finditer(squashed):
                try:
                    value = _value(m.group(1))
                except ValueError:
                    continue
                around = _words(squashed[max(0, m.start() - 120):m.start()])[-CONTEXT_WORDS:]
                around += _words(squashed[m.end():m.end() + 120])[:CONTEXT_WORDS]
                context = frozenset(w[:5] for w in around if len(w) > 2 and w not in _STOP and not w.isdigit())
                found.append(Mention(kind, value, context))
    return found


def quantities(text: str) -> dict[str, frozenset[float]]:
    """The quantities a text states, by kind: {"days": {45.0, 14.0}, "money": {4580.0}, ...}."""
    found: dict[str, set[float]] = {}
    for m in mentions(text):
        found.setdefault(m.kind, set()).add(m.value)
    return {k: frozenset(v) for k, v in found.items()}


MIN_SHARED = 2


def claim_clash(a: Sequence[Mention], b: Sequence[Mention]) -> tuple[float, list[str]]:
    """How strongly two texts state different values for the same thing: the best overlap (Jaccard) of the words
    around a quantity of `a` and one of `b` of the same kind whose values differ, at least one of them absent from
    the other text (a circular may quote the value it replaces). 0 when there is no such pair; also the kinds of
    quantity that clash."""
    va: dict[str, set[float]] = {}
    vb: dict[str, set[float]] = {}
    for m in a:
        va.setdefault(m.kind, set()).add(m.value)
    for m in b:
        vb.setdefault(m.kind, set()).add(m.value)
    best, kinds = 0.0, []
    for m in a:
        for n in b:
            if m.kind != n.kind or m.value == n.value or (m.value in vb[n.kind] and n.value in va[m.kind]):
                continue
            shared = len(m.context & n.context)
            if shared < MIN_SHARED:
                continue
            best = max(best, shared / len(m.context | n.context))
            if m.kind not in kinds:
                kinds.append(m.kind)
    return best, kinds


# ---------------------------------------------------------------- duplicates


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def shingles(text: str, size: int = SHINGLE) -> set[str]:
    words = _words(text)
    return {" ".join(words[i:i + size]) for i in range(max(1, len(words) - size + 1))}


_rng = np.random.default_rng(_SEED)
_A = _rng.integers(1, _PRIME, PERMUTATIONS, dtype=np.uint64)
_B = _rng.integers(0, _PRIME, PERMUTATIONS, dtype=np.uint64)


def minhash(text: str) -> np.ndarray:
    """A MinHash signature: per permutation (a·x + b mod p), the least hash of the text's word shingles."""
    hashed = np.array(
        [int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big") % _PRIME for s in shingles(text)],
        dtype=np.uint64,
    )
    return ((np.outer(hashed, _A) + _B) % _PRIME).min(axis=0)


def lsh_pairs(signatures: Sequence[np.ndarray], bands: int = BANDS) -> set[tuple[int, int]]:
    """Pairs of rows sharing at least one LSH band (rows that may be similar)."""
    rows = PERMUTATIONS // bands
    pairs: set[tuple[int, int]] = set()
    for band in range(bands):
        buckets: dict[bytes, list[int]] = {}
        for n, signature in enumerate(signatures):
            buckets.setdefault(signature[band * rows:(band + 1) * rows].tobytes(), []).append(n)
        for members in buckets.values():
            pairs.update(itertools.combinations(members, 2))
    return pairs


@dataclass
class DuplicateCandidate:
    a: DocumentMeta
    b: DocumentMeta
    similarity: float
    """Estimated Jaccard (MinHash)."""
    cosine: float


def document_vectors(corpus: Corpus) -> np.ndarray:
    rows = []
    for doc in corpus.documents:
        mean = np.mean([c.vector for c in corpus.chunks[doc.doc_id]], axis=0)
        rows.append(mean / (np.linalg.norm(mean) or 1.0))
    return np.array(rows)


def duplicate_candidates(corpus: Corpus, thresholds: Thresholds) -> list[DuplicateCandidate]:
    docs = corpus.documents
    signatures = [minhash(corpus.text(d.doc_id)) for d in docs]
    vectors = document_vectors(corpus)
    # Borderline pairs need the vectors' say: band more finely (more, shorter bands) so they reach the check.
    found = []
    for i, j in sorted(lsh_pairs(signatures) | lsh_pairs(signatures, bands=64)):
        a, b = docs[i], docs[j]
        if a.doc_type == "email" and b.doc_type == "email":
            continue
        jaccard = float(np.mean(signatures[i] == signatures[j]))
        cosine = float(vectors[i] @ vectors[j])
        if jaccard >= thresholds.duplicate_jaccard or (
            jaccard >= thresholds.duplicate_borderline and cosine >= thresholds.duplicate_cosine
        ):
            original, copy = ordered(a, b)
            found.append(DuplicateCandidate(original, copy, round(jaccard, 3), round(cosine, 3)))
    return sorted(found, key=lambda c: -c.similarity)


def ordered(a: DocumentMeta, b: DocumentMeta) -> tuple[DocumentMeta, DocumentMeta]:
    """(original, copy): a superseded version first, else one not titled a copy, else the earlier effective date,
    else the shorter source path (a copy's name usually adds to the original's), else doc_id."""
    def key(d: DocumentMeta) -> tuple[int, int, date, int, str, str]:
        return (0 if d.status == "superseded" else 1, 1 if re.search(r"\bcopy\b", d.title, re.I) else 0,
                d.effective_from or date.min, len(d.source_path), d.source_path, d.doc_id)
    return (a, b) if key(a) <= key(b) else (b, a)


# ---------------------------------------------------------------- conflicts


@dataclass
class RecordPassage:
    """A PLG Records row, shown as a citable passage."""

    record_id: str
    title: str
    text: str

    @property
    def chunk_id(self) -> str:
        return f"record:{self.record_id}"


@dataclass
class PairCandidate:
    """Two sources that may disagree, with the chunks to show Opus. `b` is a document or a PLG Records row."""

    a: DocumentMeta
    b: DocumentMeta | RecordPassage
    found_by: list[FoundBy]
    a_chunks: list[Chunk] = field(default_factory=list)
    b_chunks: list[Chunk] = field(default_factory=list)
    score: float = 0.0
    kinds: list[str] = field(default_factory=list)
    """Kinds of quantity on which they differ."""

    @property
    def b_id(self) -> str:
        return self.b.doc_id if isinstance(self.b, DocumentMeta) else self.b.chunk_id

    @property
    def key(self) -> tuple[str, str]:
        return (self.a.doc_id, self.b_id)

    def add(self, x: Chunk, y: Chunk | None, score: float, kinds: Iterable[str], by: FoundBy, limit: int) -> None:
        if by not in self.found_by:
            self.found_by.append(by)
        if x.chunk_id not in {c.chunk_id for c in self.a_chunks} and len(self.a_chunks) < limit:
            self.a_chunks.append(x)
        if y is not None and y.chunk_id not in {c.chunk_id for c in self.b_chunks} and len(self.b_chunks) < limit:
            self.b_chunks.append(y)
        self.score = max(self.score, score)
        self.kinds = list(dict.fromkeys([*self.kinds, *kinds]))


def same_document(a: DocumentMeta, b: DocumentMeta) -> bool:
    """Versions of one controlled document (same policy/SOP ID)."""
    return bool(a.policy_id) and a.policy_id == b.policy_id


def similarity_pairs(
    corpus: Corpus, exclude: set[frozenset[str]], thresholds: Thresholds, skip: frozenset[str] | set[str] = frozenset()
) -> dict[tuple[str, str], PairCandidate]:
    """Chunks near each other (vectors) that state different values for the same thing (`claim_clash`). Superseded
    documents are left out (they are expected to differ from what replaced them), and so are documents in `skip`
    (copies: their original stands for them)."""
    chunks = [
        c for d in corpus.documents if d.status == "current" and d.doc_id not in skip for c in corpus.chunks[d.doc_id]
    ]
    docs = {d.doc_id: d for d in corpus.documents}
    if not chunks:
        return {}
    matrix = np.array([c.vector for c in chunks], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True).clip(min=1e-9)
    stated = [mentions(c.text) for c in chunks]
    owner = np.array([c.doc_id for c in chunks])
    pairs: dict[tuple[str, str], PairCandidate] = {}
    seen: set[tuple[int, int]] = set()

    def compare(i: int, j: int) -> None:
        if (min(i, j), max(i, j)) in seen or not stated[j]:
            return
        seen.add((min(i, j), max(i, j)))
        x, y = chunks[i], chunks[j]
        da, db = docs[x.doc_id], docs[y.doc_id]
        if da.doc_id == db.doc_id or frozenset((da.doc_id, db.doc_id)) in exclude or same_document(da, db):
            return
        score, kinds = claim_clash(stated[i], stated[j])
        if score < thresholds.claim_overlap:
            return
        (da, x), (db, y) = sorted([(da, x), (db, y)], key=lambda p: p[0].doc_id)
        pair = pairs.setdefault((da.doc_id, db.doc_id), PairCandidate(da, db, []))
        pair.add(x, y, score, kinds, "similarity", thresholds.chunks_per_side)

    # Chunks that state a quantity of the same kind among the same words, whatever their vectors say.
    for i, j in claim_blocks(stated, MIN_SHARED):
        compare(i, j)
    for start in range(0, len(chunks), 512):  # blockwise, so a large corpus never holds the whole n x n matrix
        scores = matrix[start:start + 512] @ matrix.T
        for offset, row in enumerate(scores):
            i = start + offset
            if not stated[i]:
                continue
            row[owner == chunks[i].doc_id] = -1.0
            for j in np.argsort(-row)[:thresholds.neighbours]:
                j = int(j)
                if row[j] < thresholds.chunk_cosine:
                    break
                compare(i, j)
    return pairs


def claim_blocks(stated: Sequence[Sequence[Mention]], min_shared: int) -> set[tuple[int, int]]:
    """Pairs of texts with a quantity of the same kind whose surrounding words share at least `min_shared` stems:
    an inverted index on (kind, stem), so only texts that could clash are compared."""
    index: dict[tuple[str, str], set[int]] = {}
    for n, found in enumerate(stated):
        for m in found:
            for stem in m.context:
                index.setdefault((m.kind, stem), set()).add(n)
    counts: dict[tuple[int, int], int] = {}
    for members in index.values():
        if len(members) > 200:  # a stem nearly every text has says nothing about what the quantity is
            continue
        for pair in itertools.combinations(sorted(members), 2):
            counts[pair] = counts.get(pair, 0) + 1
    return {pair for pair, shared in counts.items() if shared >= min_shared}


# ---------------------------------------------------------------- lineage

POLICY_ID = re.compile(r"\bPLG-POL-\d{3}\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])|\n\s*\n|\n(?=\s*(?:[-*\u2022>|]|\d+[.)]\s))")


def sentences(text: str) -> list[str]:
    """The text's sentences, each on one line (PDF line breaks inside a sentence are joined)."""
    return [" ".join(s.split()) for s in _SENTENCE_END.split(text) if s.strip()]


@dataclass
class StaleCandidate:
    doc: DocumentMeta
    policy_id: str
    quote: str
    chunk: Chunk
    relies_on: DocumentMeta | None
    """The policy version in force on the SOP's effective date (None if none was)."""
    current: DocumentMeta


def in_force(versions: Sequence[DocumentMeta], on: date) -> DocumentMeta | None:
    dated = [v for v in versions if v.effective_from and v.effective_from <= on]
    return max(dated, key=lambda v: v.effective_from or date.min) if dated else None


def stale_documents(corpus: Corpus) -> list[StaleCandidate]:
    policies: dict[str, list[DocumentMeta]] = {}
    for d in corpus.documents:
        if d.doc_type == "policy" and d.policy_id:
            policies.setdefault(d.policy_id, []).append(d)
    found = []
    for doc in corpus.documents:
        if doc.doc_type != "sop" or doc.status != "current" or doc.effective_from is None:
            continue
        named: dict[str, tuple[str, Chunk]] = {}
        for chunk in corpus.chunks[doc.doc_id]:
            for sentence in sentences(chunk.text):
                for policy_id in POLICY_ID.findall(sentence):
                    named.setdefault(policy_id, (sentence, chunk))
        for policy_id, (quote, chunk) in named.items():
            versions = policies.get(policy_id, [])
            current = next((v for v in versions if v.status == "current"), None)
            superseded = [v for v in versions if v.status == "superseded"]
            if current is None or not superseded or current.effective_from is None:
                continue
            if doc.effective_from < current.effective_from:
                found.append(StaleCandidate(doc, policy_id, quote, chunk, in_force(versions, doc.effective_from), current))
    return found


def lineage_pairs(
    corpus: Corpus, stale: Sequence[StaleCandidate], thresholds: Thresholds
) -> dict[tuple[str, str], PairCandidate]:
    """Each stale SOP against the current version of its policy: the SOP's chunks stating quantities, each with the
    policy chunk nearest it among those stating the same kind."""
    pairs: dict[tuple[str, str], PairCandidate] = {}
    for item in stale:
        pair = PairCandidate(item.doc, item.current, ["lineage"])
        policy_chunks = [(c, mentions(c.text)) for c in corpus.chunks[item.current.doc_id]]
        matches = []
        for x in corpus.chunks[item.doc.doc_id]:
            own = mentions(x.text)
            for y, theirs in policy_chunks:
                score, kinds = claim_clash(own, theirs)
                if score > 0:
                    matches.append((score, x, y, kinds))
        for score, x, y, kinds in sorted(matches, key=lambda m: -m[0]):
            pair.add(x, y, score, kinds, "lineage", thresholds.chunks_per_side)
        if not pair.a_chunks:
            pair.a_chunks.append(item.chunk)
        pairs[pair.key] = pair
    return pairs


# ---------------------------------------------------------------- PLG Records

TENANCY_ID = re.compile(r"^TA-\d{4}-\d{5}$")
_RENT = re.compile(r"\brent\b", re.I)
_MONTHLY = re.compile(r"month", re.I)


def connect(records_db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{records_db}?mode=ro", uri=True)


def tenancy_passage(conn: sqlite3.Connection, tenancy_id: str) -> tuple[RecordPassage, float] | None:
    row = conn.execute(
        "SELECT t.tenancy_id, t.unit_id, t.tenant_id, n.name, t.trade, t.start_date, t.end_date, t.monthly_rent, "
        "t.status FROM tenancies t LEFT JOIN tenants n ON n.tenant_id = t.tenant_id WHERE t.tenancy_id = ?",
        (tenancy_id,),
    ).fetchone()
    if row is None or row[7] is None:
        return None
    tid, unit, tenant, name, trade, start, end, rent, status = row
    text = (
        f"Tenancy {tid}: unit {unit}, tenant {tenant} ({name}), trade {trade}, {start} to {end}, status {status}. "
        f"Monthly rent: S${rent:,.2f}."
    )
    return RecordPassage(tid, f"PLG Records: tenancies {tid}", text), float(rent)


def record_pairs(corpus: Corpus, records_db: Path, thresholds: Thresholds) -> dict[tuple[str, str], PairCandidate]:
    pairs: dict[tuple[str, str], PairCandidate] = {}
    passages: dict[str, tuple[RecordPassage, float] | None] = {}
    with connect(records_db) as conn:
        for doc in corpus.documents:
            for chunk in corpus.chunks[doc.doc_id]:
                tenancies = [e for e in chunk.entity_ids if TENANCY_ID.match(e)]
                if len(tenancies) != 1:  # a table of many tenancies says which rent is whose only row by row
                    continue
                (tenancy_id,) = tenancies
                if tenancy_id not in passages:
                    passages[tenancy_id] = tenancy_passage(conn, tenancy_id)
                record = passages[tenancy_id]
                if record is None:
                    continue
                passage, rent = record
                if not _RENT.search(chunk.text):
                    continue
                stated = {
                    amount
                    for sentence in sentences(chunk.text)
                    if _MONTHLY.search(sentence)
                    for amount in quantities(sentence).get("money", frozenset())
                }
                if stated and any(abs(amount - rent) >= 0.01 for amount in stated):
                    pair = pairs.setdefault((doc.doc_id, passage.chunk_id), PairCandidate(doc, passage, []))
                    pair.add(chunk, None, 1.0, ["money"], "records", thresholds.chunks_per_side)
    return pairs


# ---------------------------------------------------------------- superseded definitions

DEFINITION_DOC_TYPES = frozenset({"report", "deck"})
_FIGURE = re.compile(r"\d")


@dataclass
class DefinitionCandidate:
    doc: DocumentMeta
    chunks: list[Chunk]
    concepts: list[str]
    """Glossary concepts with a superseded version that the chunks state a figure for."""


def term_labels(versions: Sequence[GlossaryTerm]) -> list[str]:
    labels = {label for v in versions for label in [v.pref_label, *(v.alt_labels or [])]}
    return sorted(labels, key=len, reverse=True)


def changed_concepts(glossary: Glossary) -> dict[str, re.Pattern[str]]:
    """Concepts whose definition changed (a superseded version exists), each with a pattern of its labels."""
    out = {}
    for concept in glossary.concepts():
        versions = glossary.versions(concept)
        if any(v.status == "superseded" for v in versions) and glossary.current(concept):
            labels = "|".join(re.escape(label) for label in term_labels(versions))
            out[concept] = re.compile(rf"(?<!\w)(?:{labels})(?!\w)", re.I)
    return out


def definition_candidates(corpus: Corpus, glossary: Glossary, max_chunks: int = 6) -> list[DefinitionCandidate]:
    changed = changed_concepts(glossary)
    found = []
    for doc in corpus.documents:
        if doc.doc_type not in DEFINITION_DOC_TYPES:
            continue
        chunks: list[Chunk] = []
        concepts: list[str] = []
        for chunk in corpus.chunks[doc.doc_id]:
            lines = [line for line in chunk.text.splitlines() if _FIGURE.search(line)]
            hit = [c for c, pattern in changed.items() if any(pattern.search(line) for line in lines)]
            if hit:
                chunks.append(chunk)
                concepts += [c for c in hit if c not in concepts]
        if chunks:
            found.append(DefinitionCandidate(doc, chunks[:max_chunks], concepts))
    return found


# ---------------------------------------------------------------- all together


@dataclass
class Candidates:
    duplicates: list[DuplicateCandidate]
    conflicts: list[PairCandidate]
    """Document pairs (or document vs record) to judge, best first, at most `max_pairs`."""
    definitions: list[DefinitionCandidate]
    stale: list[StaleCandidate]


def candidates(
    store: SearchStore | Corpus, records_db: Path, glossary: Glossary, thresholds: Thresholds = Thresholds()
) -> Candidates:
    corpus = store if isinstance(store, Corpus) else Corpus.of(store)
    duplicates = duplicate_candidates(corpus, thresholds)
    exclude = {frozenset((d.a.doc_id, d.b.doc_id)) for d in duplicates}
    copies = {d.b.doc_id for d in duplicates if d.similarity >= thresholds.copy_jaccard and not same_document(d.a, d.b)}
    stale = stale_documents(corpus)
    merged: dict[tuple[str, str], PairCandidate] = {}
    for source in (lineage_pairs(corpus, stale, thresholds), record_pairs(corpus, records_db, thresholds),
                   similarity_pairs(corpus, exclude, thresholds, skip=copies)):
        for key, pair in source.items():
            known = merged.get(key) or merged.get((key[1], key[0]))
            if known is None:
                merged[key] = pair
                continue
            ours, theirs = (pair.a_chunks, pair.b_chunks) if known.key == key else (pair.b_chunks, pair.a_chunks)
            for by in pair.found_by:
                for x in ours:
                    known.add(x, None, pair.score, pair.kinds, by, thresholds.chunks_per_side)
                for y in theirs:
                    if y.chunk_id not in {c.chunk_id for c in known.b_chunks} and len(known.b_chunks) < thresholds.chunks_per_side:
                        known.b_chunks.append(y)
    rank = {"lineage": 0, "records": 1, "similarity": 2}
    ordered_pairs = sorted(merged.values(), key=lambda p: (min(rank[b] for b in p.found_by), -p.score, p.key))
    return Candidates(duplicates, ordered_pairs[:thresholds.max_pairs], definition_candidates(corpus, glossary), stale)
