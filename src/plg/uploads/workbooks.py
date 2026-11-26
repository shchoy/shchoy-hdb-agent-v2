"""Excel uploads (#105): an officer's workbooks as their own read-only catalog for the data agent.

An uploaded .xlsx is cleaned exactly like the Excel trackers (`data.trackers.read_workbook`: merged headers, title and
note rows, text dates, formula columns and formula-only rows or sheets). Its text (titles, notes and text cells) is
screened for prompt injection, as the data agent reads it. Its tables get names unique among the officer's
workbooks (a second copy's table gets `_2`) and are written to `tables.duckdb` in the upload's folder, with
`workbook.json` (the screened `Workbook`).

All of an officer's workbooks are then combined into `<officer>/workbooks.duckdb` (rebuilt after every upload or
deletion, replaced atomically), which the data agent's warehouse attaches read-only as `uploads`, in that officer's
runs only.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import duckdb

from plg.data.trackers import (
    CATALOG_TABLE, SheetTable, Workbook, create_catalog, describe, read_workbook, sql_text, write_workbook,
)
from plg.data.sqlcheck import UPLOADS
from plg.guardrails import injection
from plg.ingest.extract import Block, ParsedDoc

TABLES = "tables.duckdb"
SPEC = "workbook.json"
COMBINED = "workbooks.duckdb"


def read(path: Path, taken: Iterable[str]) -> tuple[Workbook, list[SheetTable], frozenset[str]]:
    """The workbook cleaned and screened, its tables renamed apart from `taken`, and the rules of anything removed.
    A planted instruction in a text cell is replaced by the removal marker in the data itself."""
    workbook, tables = read_workbook(path, path.name)
    removed: set[str] = set()

    def clean(text: str) -> str:
        screening = injection.screen(text)
        removed.update(h.rule for h in screening.hits)
        return screening.text

    workbook.titles = [clean(t) for t in workbook.titles]
    workbook.notes = [clean(n) for n in workbook.notes]
    for table in tables:
        table.rows = [[clean(v) if isinstance(v, str) else v for v in row] for row in table.rows]
    used = set(taken)
    for table, spec in zip(tables, workbook.tables, strict=True):
        name, n = table.name, 1
        while name in used:
            n += 1
            name = f"{table.name}_{n}"
        used.add(name)
        table.name = spec.name = name
    return workbook, tables, frozenset(removed)


def save(folder: Path, key: str, workbook: Workbook, tables: list[SheetTable]) -> None:
    """The upload's own tables and description, in its folder."""
    con = duckdb.connect(str(folder / TABLES))
    try:
        create_catalog(con)
        write_workbook(con, workbook, tables, key)
    finally:
        con.close()
    (folder / SPEC).write_text(workbook.model_dump_json())


def spec(folder: Path) -> Workbook | None:
    """The upload's screened workbook description, as saved."""
    path = folder / SPEC
    return Workbook.model_validate_json(path.read_text()) if path.is_file() else None


def parsed(workbook: Workbook) -> ParsedDoc:
    """The workbook's description as a document: what the source viewer shows and knowledge search finds."""
    lines = describe([workbook], UPLOADS).splitlines()
    return ParsedDoc([Block(text=line.strip(), level=1 if i == 0 else 0) for i, line in enumerate(lines)], title=None)


def combine(owner_dir: Path, folders: Iterable[Path]) -> None:
    """Rebuild the officer's catalog from each upload's tables (none left: no catalog)."""
    target = owner_dir / COMBINED
    sources = [f / TABLES for f in folders if (f / TABLES).is_file()]
    if not sources:
        target.unlink(missing_ok=True)
        return
    tmp = owner_dir / f".{COMBINED}.tmp"
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        create_catalog(con)
        for n, source in enumerate(sources):
            alias = f"upload_{n}"
            con.execute(f"ATTACH {sql_text(source)} AS {alias} (READ_ONLY)")
            names = con.execute(
                "SELECT table_name FROM duckdb_tables() WHERE database_name = ? AND table_name <> ?",
                [alias, CATALOG_TABLE],
            ).fetchall()
            for (name,) in names:
                con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM {alias}."{name}"')
            con.execute(f"INSERT INTO {CATALOG_TABLE} SELECT * FROM {alias}.{CATALOG_TABLE}")
            con.execute(f"DETACH {alias}")
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(tmp, target)
    tmp.with_name(f"{tmp.name}.wal").unlink(missing_ok=True)
