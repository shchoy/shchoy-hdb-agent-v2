"""DuckDB over the PLG Records SQLite database, attached read-only."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from plg.data.sqlcheck import BLOCKED_TABLES, CATALOG, SqlRejected, check_sql

MAX_ROWS = 500
"""Rows fetched per query; a bigger result is flagged as truncated."""

Cell = str | int | float | None


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Cell]]
    """At most MAX_ROWS rows."""
    truncated: bool
    tables: frozenset[str]


def cell(value: Any) -> Cell:
    if value is None or isinstance(value, (str, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


class Warehouse:
    """Opened on first use, so plg-api starts without the DuckDB sqlite extension (downloaded once, then cached).

    The database is attached read-only, then the connection is locked: no file, network or extension access.
    """

    def __init__(self, records_db: Path) -> None:
        self._records_db = records_db
        self._lock = threading.Lock()
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._tables: frozenset[str] = frozenset()

    def _open(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._connection is None:
                con = duckdb.connect(":memory:")
                con.execute("INSTALL sqlite")
                con.execute("LOAD sqlite")
                con.execute(f"ATTACH '{self._records_db}' AS {CATALOG} (TYPE sqlite, READ_ONLY)")
                names = con.execute(
                    "SELECT table_name FROM duckdb_tables() WHERE database_name = ?", [CATALOG]
                ).fetchall()
                self._tables = frozenset(n.lower() for (n,) in names) - BLOCKED_TABLES
                con.execute("SET enable_external_access = false")
                con.execute("SET lock_configuration = true")
                self._connection = con
            return self._connection

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        """A connection of its own (they share the database, not the session), with PLG Records as the default."""
        cursor = self._open().cursor()
        cursor.execute(f"USE {CATALOG}.main")
        return cursor

    @property
    def tables(self) -> frozenset[str]:
        self._open()
        return self._tables

    def run(self, sql: str, as_of: date) -> QueryResult:
        """Validate, dry-run with EXPLAIN, then execute `sql` (`$as_of` is bound to `as_of`).

        Raises SqlRejected when the validator or the dry run refuses it."""
        self._open()
        tables = check_sql(sql, self._tables)
        params = {"as_of": as_of.isoformat()} if "$as_of" in sql else {}
        cursor = self._cursor()
        try:
            cursor.execute(f"EXPLAIN {sql}", params)
        except duckdb.Error as e:
            raise SqlRejected(f"The query does not plan: {str(e).splitlines()[0]}") from e
        try:
            cursor.execute(sql, params)
            fetched = cursor.fetchmany(MAX_ROWS + 1)
        except duckdb.Error as e:
            raise SqlRejected(f"The query failed: {str(e).splitlines()[0]}") from e
        columns = [d[0] for d in cursor.description]
        return QueryResult(
            columns=columns,
            rows=[[cell(v) for v in row] for row in fetched[:MAX_ROWS]],
            truncated=len(fetched) > MAX_ROWS,
            tables=tables,
        )

    def dry_run(self, sql: str, as_of: date) -> None:
        """Validate and EXPLAIN `sql` without running it."""
        self._open()
        check_sql(sql, self._tables)
        try:
            self._cursor().execute(f"EXPLAIN {sql}", {"as_of": as_of.isoformat()} if "$as_of" in sql else {})
        except duckdb.Error as e:
            raise SqlRejected(f"The query does not plan: {str(e).splitlines()[0]}") from e
