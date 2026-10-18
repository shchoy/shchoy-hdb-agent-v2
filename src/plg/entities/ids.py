"""Strict business-ID formats of the PLG Records entities, and the text normaliser used to match names."""

from __future__ import annotations

import re

ID_PATTERNS: dict[str, str] = {
    "Town": r"[A-Z]{2}",
    "NeighbourhoodCentre": r"NC-[A-Z]{2}-\d+",
    "Block": r"[A-Z]{2}\d{3}",
    "Unit": r"U-[A-Z]{2}\d{3}-\d{2}-\d{2}",
    "Tenant": r"T-\d{5}",
    "Tenancy": r"TA-\d{4}-\d{5}",
    "RentInvoice": r"INV-\d{4}-\d{6}",
    "Inspection": r"INSP-\d{4}-\d{4}",
    "FeedbackCase": r"FB-\d{4}-\d{5}",
    "IemsTicket": r"IEMS-\d{4}-\d{4}",
    "Application": r"APP-\d{4}-\d{4}",
    "Task": r"TSK-\d{4}-\d{4}",
    "Letter": r"LTR-\d{4}-\d{5}",
    "Staff": r"S\d{2}",
    "DefectCategory": r"[A-Z]{3}",
}
"""Labels whose IDs have a fixed shape. Trade, Team and Vendor are identified by their names."""

_COMPILED = {label: re.compile(pattern) for label, pattern in ID_PATTERNS.items()}

# Free-text lookups skip the short, generic shapes (towns, staff, categories): they'd match everyday words.
_DISTINCTIVE = [label for label in ID_PATTERNS if label not in {"Town", "Staff", "DefectCategory", "Block"}]
_IN_TEXT = re.compile(
    r"(?<![A-Za-z0-9-])(" + "|".join(ID_PATTERNS[label] for label in [*_DISTINCTIVE, "Block"]) + r")(?![A-Za-z0-9-])"
)


def is_valid_id(label: str, node_id: str) -> bool:
    """True if `node_id` has the strict format of `label`'s IDs (labels without a format accept any text)."""
    pattern = _COMPILED.get(label)
    return pattern.fullmatch(node_id) is not None if pattern else bool(node_id.strip())


def label_for_id(node_id: str) -> str | None:
    """The label an ID's format belongs to, or None when it fits none (or, like `BV`, several)."""
    labels = [label for label in ID_PATTERNS if _COMPILED[label].fullmatch(node_id)]
    return labels[0] if len(labels) == 1 else None


def find_ids(text: str) -> list[str]:
    """Business IDs written in free text, in order and without repeats."""
    return list(dict.fromkeys(m.group(1) for m in _IN_TEXT.finditer(text)))


def search_name(*parts: str) -> str:
    """Case-, punctuation- and spacing-insensitive form used to match names: "Blk 214 #01-32" -> "blk 214 01 32"."""
    return " ".join(re.findall(r"[a-z0-9]+", " ".join(parts).casefold()))
