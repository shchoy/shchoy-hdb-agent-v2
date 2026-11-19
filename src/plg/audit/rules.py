"""Deterministic ontology rule checks over PLG Records (read-only) and the index metadata. No Claude.

- overlapping_tenancies: two tenancies of one unit whose periods overlap. Every status counts: the data has no
  overlap among ended (Expired, Terminated, Renewed) tenancies, so nothing needs excluding, and an ended tenancy
  overlapping another is as much a records error as two live ones.
- two_current_policy_versions: two current indexed documents with the same policy ID.
- trade_not_allowed: a live tenancy (Active or Pending Commencement) whose trade the ontology doesn't allow in its
  unit's type (`plg:trades` allowed_unit_types, matched as whole names: "Shop" is not "Shop with Living Quarters").
- duplicate_tenants: tenants sharing a business registration number (BRN).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from plg.audit.model import RuleViolation
from plg.ontology.generated.models import Trade
from plg.ontology.vocab import VocabIndex, normalise
from plg.search.models import DocumentMeta

LIVE = ("Active", "Pending Commencement")


def _connect(records_db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{records_db}?mode=ro", uri=True)


def overlapping_tenancies(conn: sqlite3.Connection) -> list[RuleViolation]:
    rows = conn.execute(
        "SELECT a.unit_id, a.tenancy_id, a.status, a.start_date, a.end_date, b.tenancy_id, b.status, b.start_date, "
        "b.end_date FROM tenancies a JOIN tenancies b ON a.unit_id = b.unit_id AND a.tenancy_id < b.tenancy_id "
        "AND a.start_date <= b.end_date AND b.start_date <= a.end_date ORDER BY a.unit_id, a.tenancy_id"
    ).fetchall()
    return [
        RuleViolation(
            rule="overlapping_tenancies", entity_ids=[unit, ta, tb],
            detail=f"Unit {unit} has overlapping tenancies: {ta} ({sa}, {fa} to {ea}) and {tb} ({sb}, {fb} to {eb}).",
        )
        for unit, ta, sa, fa, ea, tb, sb, fb, eb in rows
    ]


def duplicate_tenants(conn: sqlite3.Connection) -> list[RuleViolation]:
    rows = conn.execute(
        "SELECT brn, tenant_id, name FROM tenants WHERE brn IS NOT NULL AND TRIM(brn) <> '' AND brn IN "
        "(SELECT brn FROM tenants WHERE brn IS NOT NULL GROUP BY brn HAVING COUNT(*) > 1) ORDER BY brn, tenant_id"
    ).fetchall()
    groups: dict[str, list[tuple[str, str]]] = {}
    for brn, tenant_id, name in rows:
        groups.setdefault(brn, []).append((tenant_id, name))
    return [
        RuleViolation(
            rule="duplicate_tenants", entity_ids=[t for t, _ in tenants],
            detail=f"Tenants {', '.join(f'{t} ({n})' for t, n in tenants)} share BRN {brn}.",
        )
        for brn, tenants in groups.items()
    ]


def allowed_unit_types(vocab: VocabIndex) -> dict[str, frozenset[str]]:
    """Allowed unit types per trade name (normalised), from the ontology's trade concepts."""
    allowed: dict[str, frozenset[str]] = {}
    for trade in vocab.concepts("plg:trades", Trade):
        if trade.allowed_unit_types:
            types = frozenset(normalise(t) for t in trade.allowed_unit_types)
            for name in (trade.notation, trade.pref_label):
                if name:
                    allowed[normalise(name)] = types
    return allowed


def trade_not_allowed(conn: sqlite3.Connection, vocab: VocabIndex) -> list[RuleViolation]:
    allowed = allowed_unit_types(vocab)
    rows = conn.execute(
        f"SELECT t.tenancy_id, t.unit_id, t.trade, u.unit_type FROM tenancies t JOIN units u ON u.unit_id = t.unit_id "
        f"WHERE t.status IN ({', '.join('?' for _ in LIVE)}) ORDER BY t.tenancy_id",
        LIVE,
    ).fetchall()
    found = []
    for tenancy_id, unit_id, trade, unit_type in rows:
        types = allowed.get(normalise(trade or ""))
        if types is None or unit_type is None or normalise(unit_type) in types:
            continue  # a trade the ontology doesn't constrain is not a violation
        found.append(RuleViolation(
            rule="trade_not_allowed", entity_ids=[tenancy_id, unit_id, trade],
            detail=f"Tenancy {tenancy_id} runs a {trade} in {unit_id}, a {unit_type}; "
                   f"{trade} is allowed only in: {', '.join(sorted(types))}.",
        ))
    return found


def two_current_policy_versions(documents: Sequence[DocumentMeta]) -> list[RuleViolation]:
    current: dict[str, list[DocumentMeta]] = {}
    for doc in documents:
        if doc.policy_id and doc.status == "current":
            current.setdefault(doc.policy_id, []).append(doc)
    return [
        RuleViolation(
            rule="two_current_policy_versions", entity_ids=[policy_id, *(d.doc_id for d in docs)],
            detail=f"{policy_id} has {len(docs)} current versions: "
                   + ", ".join(f"v{d.version} ({d.title}, {d.doc_id})" for d in docs) + ".",
        )
        for policy_id, docs in sorted(current.items())
        if len(docs) > 1
    ]


def check_rules(records_db: Path, vocab: VocabIndex, documents: Sequence[DocumentMeta]) -> list[RuleViolation]:
    with _connect(records_db) as conn:
        return [
            *overlapping_tenancies(conn), *two_current_policy_versions(documents), *trade_not_allowed(conn, vocab),
            *duplicate_tenants(conn),
        ]
