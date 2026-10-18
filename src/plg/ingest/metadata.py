"""Document metadata at ingestion: type, policy ID and version, effective dates, lineage, entity tags."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from plg.ontology.generated.models import Trade
from plg.ontology.vocab import load_vocab
from plg.search.models import DocStatus, DocumentMeta, EntityRecord

# First match wins; values are notations of the plg:document_types vocabulary.
_DOC_TYPES: list[tuple[str, str]] = [
    (r"\.eml$", "email"),
    (r"\.pptx$", "deck"),
    (r"PLG-POL-\d", "policy"),
    (r"PLG-SOP-\d", "sop"),
    (r"(^|/)TPL-", "template"),
    (r"Circular", "circular"),
    (r"Minutes", "minutes"),
    (r"Guidelines", "guideline"),
    (r"FAQ", "faq"),
    (r"Precedent", "precedent_compendium"),
    (r"(^|/)LOD_", "letter"),
    (r"Tender_Notice", "tender_notice"),
    (r"Scan_TA", "tenancy_agreement"),
    (r"Report", "report"),
    (r"\.xlsx$", "tracker"),
    (r"^exports/", "system_export"),
    (r"^docs/notes/", "note"),
]

_CONTROLLED_ID = re.compile(r"^(PLG-(?:POL|SOP)-\d{3}|TPL-[A-Z]{3}-\d{2})$")
_FILENAME_VERSION = re.compile(r"(PLG-(?:POL|SOP)-\d{3}|TPL-[A-Z]{3}-\d{2}).*_v(\d+(?:\.\d+)*)\.\w+$")

# Strict business-ID patterns (PLG Records and corpus references).
ENTITY_ID = re.compile(
    r"\b(?:"
    r"TA-\d{4}-\d{5}|T-\d{5}|U-[A-Z]{2}\d{3}-\d{2}-\d{2}|NC-[A-Z]{2}-\d|PLG-(?:POL|SOP)-\d{3}|TPL-[A-Z]{3}-\d{2}"
    r"|IEMS-\d{4}-\d{4}|INSP-\d{4}-\d{4}|APP-\d{4}-\d{4}|LTR-\d{4}-\d{5}|FB-\d{4}-\d{5}|TSK-\d{4}-\d{4}"
    r"|INV-\d{4}-\d{6}|PAY-\d{8}|PC-\d{4}-\d{3}|PLG-INC-\d{4}-\d{3}"
    r")\b"
)
_UNIT_BLOCK = re.compile(r"\bU-([A-Z]{2}\d{3})-\d{2}-\d{2}\b")


def doc_type_for(rel_path: str) -> str:
    for pattern, doc_type in _DOC_TYPES:
        if re.search(pattern, rel_path):
            return doc_type
    return "note"


def parse_date(text: str) -> date | None:
    """The first date in `text`: "1 April 2026", "1 Mar 2024" or "2026-04-01"."""
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text):
        return date.fromisoformat(m[1])
    if m := re.search(r"\b(\d{1,2} [A-Z][a-z]{2,8} \d{4})\b", text):
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(m[1], fmt).date()
            except ValueError:
                pass
    return None


@dataclass(frozen=True)
class ControlMeta:
    policy_id: str | None
    version: str | None
    effective_from: date | None
    effective_to: date | None


def control_meta(fields: dict[str, str], rel_path: str) -> ControlMeta:
    """Policy ID, version and effective period from the document-control block (or the file name)."""
    policy_id = fields.get("Document ID", "").strip()
    version = fields.get("Version", "").strip() or None
    if not _CONTROLLED_ID.match(policy_id):
        policy_id = ""
    if m := _FILENAME_VERSION.search(rel_path):
        policy_id, version = policy_id or m[1], version or m[2]
    effective = fields.get("Effective date") or fields.get("Effective") or ""
    start, _, end = effective.partition(" to ")
    return ControlMeta(
        policy_id=policy_id or None,
        version=version if policy_id else None,
        effective_from=parse_date(start),
        effective_to=parse_date(end) if end else None,
    )


def _version_key(version: str | None) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version or ""))


def lifecycle(docs: Sequence[DocumentMeta]) -> dict[str, tuple[DocStatus, date | None]]:
    """(status, effective_to) per doc_id. Within a policy ID the highest version is current; each earlier
    version is superseded and ends the day before its successor takes effect."""
    result: dict[str, tuple[DocStatus, date | None]] = {d.doc_id: ("current", d.effective_to) for d in docs}
    by_policy: defaultdict[str, list[DocumentMeta]] = defaultdict(list)
    for d in docs:
        if d.policy_id and d.version:
            by_policy[d.policy_id].append(d)
    for versions in by_policy.values():
        versions.sort(key=lambda d: _version_key(d.version))
        for earlier, later in zip(versions, versions[1:], strict=False):
            end = later.effective_from - timedelta(days=1) if later.effective_from else earlier.effective_to
            result[earlier.doc_id] = ("superseded", end)
    return result


@dataclass(frozen=True)
class Tags:
    entity_ids: list[str]
    town: list[str]
    nc: list[str]
    trade: list[str]


class EntityTagger:
    """Finds business IDs and known names in text, and places them in towns and NCs via PLG Records."""

    def __init__(
        self,
        entities: Sequence[EntityRecord],
        block_nc: dict[str, str],
        nc_town: dict[str, str],
    ) -> None:
        self._block_nc = block_nc
        self._nc_town = nc_town
        self._by_variant: dict[str, list[EntityRecord]] = defaultdict(list)
        for e in entities:
            for variant in {e.name, *e.variants}:
                if len(variant) >= 4:
                    self._by_variant[variant.casefold()].append(e)
        # Trades get their own pass: they often sit inside a tenant's name ("Golden Leaf Minimart").
        trades = {v for v, es in self._by_variant.items() if any(e.entity_type == "Trade" for e in es)}
        self._patterns = [_alternation(trades), _alternation(set(self._by_variant) - trades)]

    def tag(self, text: str) -> Tags:
        ids: dict[str, None] = dict.fromkeys(ENTITY_ID.findall(text))
        town: dict[str, None] = {}
        nc: dict[str, None] = {}
        trade: dict[str, None] = {}
        matches = [m[1].casefold() for pattern in self._patterns for m in pattern.finditer(text)]
        for variant in matches:
            for e in self._by_variant[variant]:
                match e.entity_type:
                    case "Trade":
                        trade[e.entity_id] = None
                    case "Town":
                        town[e.entity_id] = None
                    case _:
                        ids[e.entity_id] = None
        for block in _UNIT_BLOCK.findall(text):
            if block in self._block_nc:
                nc[self._block_nc[block]] = None
        for entity_id in ids:
            if entity_id.startswith("NC-"):
                nc[entity_id] = None
        for nc_id in nc:
            if nc_id in self._nc_town:
                town[self._nc_town[nc_id]] = None
        return Tags(list(ids), list(town), list(nc), list(trade))


def _alternation(names: set[str]) -> re.Pattern[str]:
    """Whole-word, case-insensitive match of any name, longest first."""
    ordered = sorted(names, key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in ordered) + r")(?![\w-])", re.I)


def _company_variants(name: str) -> list[str]:
    short = re.sub(r"\s+(Pte\.? Ltd\.?|Ltd\.?|LLP)$", "", name)
    return [name, short] if short != name else [name]


def load_entity_spine(records_db: Path) -> tuple[list[EntityRecord], EntityTagger]:
    """Name variants of towns, NCs, tenants, staff and trades, and a tagger over them."""
    uri = f"file:{records_db}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        towns = db.execute("SELECT town_code, town_name FROM towns").fetchall()
        ncs = db.execute("SELECT nc_id, nc_name, town_code FROM neighbourhood_centres").fetchall()
        tenants = db.execute("SELECT tenant_id, name FROM tenants").fetchall()
        staff = db.execute("SELECT staff_id, name FROM staff").fetchall()
        blocks = db.execute("SELECT block_id, nc_id FROM blocks").fetchall()
    trades = load_vocab().concepts("plg:trades", Trade)
    entities: list[EntityRecord] = [
        *(EntityRecord(entity_id=c, entity_type="Town", name=n, variants=[n]) for c, n in towns),
        *(EntityRecord(entity_id=i, entity_type="NeighbourhoodCentre", name=n, variants=[n]) for i, n, _ in ncs),
        *(EntityRecord(entity_id=i, entity_type="Tenant", name=n, variants=_company_variants(n)) for i, n in tenants),
        *(EntityRecord(entity_id=i, entity_type="Staff", name=n, variants=[n]) for i, n in staff),
        *(
            EntityRecord(entity_id=t.notation or t.pref_label, entity_type="Trade", name=t.pref_label,
                         variants=_dedupe([t.pref_label, *(t.alt_labels or [])]))
            for t in trades
        ),
    ]
    tagger = EntityTagger(entities, block_nc=dict(blocks), nc_town={i: t for i, _, t in ncs})
    return entities, tagger


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
