"""Validation of agent-written SQL, before anything runs.

Only a single SELECT is accepted, reading only tables of PLG Records that the data agent may see. DuckDB parses
the statement (`json_serialize_sql` accepts SELECT statements alone, which rejects writes, PRAGMA, COPY, ATTACH
and the like); the parsed tree is then walked for every table it reads.
"""

from __future__ import annotations

import json
from typing import Any

import duckdb

CATALOG = "rec"
"""Where the SQLite records database is attached."""

BLOCKED_TABLES = frozenset({"staff"})
"""Tables of PLG Records the data agent may not read (staff contact details are not for analysis)."""


class SqlRejected(ValueError):
    """The SQL is not an allowed read-only query. The message says why, for the agent to correct it."""


def check_sql(sql: str, tables: frozenset[str]) -> frozenset[str]:
    """The tables `sql` reads. Raises SqlRejected unless it is one SELECT over only `tables`."""
    if not sql.strip():
        raise SqlRejected("The SQL is empty.")
    parsed = json.loads(duckdb.connect(":memory:").execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])  # type: ignore[index]
    if parsed.get("error"):
        message = str(parsed.get("error_message", ""))
        if "Only SELECT" in message:
            raise SqlRejected("Only read-only SELECT queries are allowed; this statement would change data or settings.")
        raise SqlRejected(f"The SQL does not parse: {message.splitlines()[0] if message else 'syntax error'}")
    if len(parsed["statements"]) != 1:
        raise SqlRejected("Send exactly one SELECT statement.")
    read: set[str] = set()
    ctes: set[str] = set()
    _walk(parsed["statements"][0], tables, read, ctes)
    return frozenset(read)


def _walk(node: Any, tables: frozenset[str], read: set[str], ctes: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, tables, read, ctes)
        return
    if not isinstance(node, dict):
        return
    for entry in node.get("cte_map", {}).get("map", []):
        ctes.add(entry["key"].lower())
    kind = node.get("type")
    if kind == "TABLE_FUNCTION":
        raise SqlRejected("Table functions are not allowed; read only the PLG Records tables.")
    if kind == "BASE_TABLE":
        _check_table(node, tables, read, ctes)
    for value in node.values():
        _walk(value, tables, read, ctes)


def _check_table(node: dict[str, Any], tables: frozenset[str], read: set[str], ctes: set[str]) -> None:
    name = node["table_name"].lower()
    catalog, schema = node["catalog_name"].lower(), node["schema_name"].lower()
    if not catalog and not schema and name in ctes:
        return
    if catalog not in ("", CATALOG) or schema not in ("", "main"):
        raise SqlRejected(f"Table {'.'.join(p for p in (catalog, schema, name) if p)} is not available.")
    if name in BLOCKED_TABLES or name not in tables:
        raise SqlRejected(f"Table {name} is not available. Available tables: {', '.join(sorted(tables))}.")
    read.add(name)
