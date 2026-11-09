"""DuckDB over the PLG Records SQLite database and the Excel trackers database, both attached read-only."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from plg.data.sqlcheck import BLOCKED_TABLES, CATALOG, TRACKERS, SqlRejected, check_sql
from plg.data.trackers import CATALOG_TABLE, Workbook

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

    The databases are attached read-only, then the connection is locked: no file, network or extension access.
    The trackers database (written by `plg sync`) is optional; a sync after opening is seen on the next start.
    """

    def __init__(self, records_db: Path, trackers_db: Path | None = None) -> None:
        self._records_db = records_db
        self._trackers_db = trackers_db
        self._lock = threading.Lock()
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._tables: frozenset[str] = frozenset()
        self._workbooks: list[Workbook] = []

    @property
    def records_db(self) -> Path:
        return self._records_db

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
                if self._trackers_db and self._trackers_db.exists():
                    self._attach_trackers(con, self._trackers_db)
                con.execute("SET enable_external_access = false")
                con.execute("SET lock_configuration = true")
                self._connection = con
            return self._connection

    def _attach_trackers(self, con: duckdb.DuckDBPyConnection, path: Path) -> None:
        con.execute(f"ATTACH '{path}' AS {TRACKERS} (READ_ONLY)")
        specs = con.execute(f"SELECT spec FROM {TRACKERS}.{CATALOG_TABLE} ORDER BY path").fetchall()
        self._workbooks = [Workbook.model_validate_json(spec) for (spec,) in specs]
        self._tables |= {f"{TRACKERS}.{t.name}" for wb in self._workbooks for t in wb.tables}

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        """A connection of its own (they share the database, not the session), with PLG Records as the default."""
        cursor = self._open().cursor()
        cursor.execute(f"USE {CATALOG}.main")
        return cursor

    @property
    def tables(self) -> frozenset[str]:
        self._open()
        return self._tables

    @property
    def trackers(self) -> list[Workbook]:
        """The Excel trackers loaded by the last `plg sync` (none when it has not run)."""
        self._open()
        return self._workbooks

    def _plan(self, sql: str, as_of: date) -> tuple[duckdb.DuckDBPyConnection, dict[str, str], frozenset[str]]:
        """Validate `sql` and EXPLAIN it on a fresh cursor. Returns the cursor, the parameters and the tables read."""
        self._open()
        tables = check_sql(sql, self._tables)
        params = {"as_of": as_of.isoformat()} if "$as_of" in sql else {}
        cursor = self._cursor()
        try:
            cursor.execute(f"EXPLAIN {sql}", params)
        except duckdb.Error as e:
            raise SqlRejected(f"The query does not plan: {str(e).splitlines()[0]}") from e
        return cursor, params, tables

    def run(self, sql: str, as_of: date) -> QueryResult:
        """Validate, dry-run with EXPLAIN, then execute `sql` (`$as_of` is bound to `as_of`).

        Raises SqlRejected when the validator or the dry run refuses it."""
        cursor, params, tables = self._plan(sql, as_of)
        try:
            cursor.execute(sql, params)
            fetched = cursor.fetchmany(MAX_ROWS + 1)
        except duckdb.Error as e:
            raise SqlRejected(f"The query failed: {str(e).splitlines()[0]}") from e
        return QueryResult(
            columns=[d[0] for d in cursor.description],
            rows=[[cell(v) for v in row] for row in fetched[:MAX_ROWS]],
            truncated=len(fetched) > MAX_ROWS,
            tables=tables,
        )

    def dry_run(self, sql: str, as_of: date) -> None:
        """Validate and EXPLAIN `sql` without running it."""
        self._plan(sql, as_of)
