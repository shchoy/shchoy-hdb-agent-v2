"""The hand-maintained Excel trackers, cleaned into DuckDB tables at ingestion (`plg sync`).

The workbooks were written by a script and never opened in Excel, so formula cells hold no saved value. Nothing
derived from a formula is trusted: formula columns are not loaded (their formula is kept, in column names, for the
data agent to compute in SQL), rows of formulas only (TOTAL rows) are dropped, and sheets that are mostly formulas
(summary pivots) are not loaded at all. The preparer's own text rows ("Notes", "Static check: ...") are kept.

Cleaning:
- a header of two rows with merged cells (Units › Total) becomes one name per column (units_total);
- title rows above the header and text rows below the table become notes;
- dates typed as text (30/09/26) are read day-first;
- sheets of one workbook with the same header (one tab per officer) become one table with a `sheet` column.

The tables and a `_workbooks` catalog (one JSON `Workbook` per file, describing them) are written to a new DuckDB
file that then replaces the old one, so a reader never sees a half-written database.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal

import duckdb
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel

CATALOG_TABLE = "_workbooks"
"""Describes the loaded workbooks; not queryable by the data agent."""

ColumnType = Literal["BIGINT", "DOUBLE", "DATE", "VARCHAR"]

TEXT_DATE_FORMATS = ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y", "%d %b %y")
"""Dates typed as text, read day-first (Singapore)."""

FORMULA_SHOWN = 200
"""Characters of a formula kept in a note."""


class Column(BaseModel):
    name: str
    header: str
    type: ColumnType


class FormulaColumn(BaseModel):
    """A column of formulas without saved values: not loaded. `formula` is its first row's, in column names."""

    name: str
    header: str
    formula: str


class TrackerTable(BaseModel):
    name: str
    sheets: list[str]
    rows: int
    columns: list[Column]
    formulas: list[FormulaColumn]
    cleaning: list[str]
    """What was changed on the way in (text dates read, rows dropped, ...)."""


class SkippedSheet(BaseModel):
    sheet: str
    reason: str


class Workbook(BaseModel):
    path: str
    """Relative to the corpus directory."""
    titles: list[str]
    notes: list[str]
    tables: list[TrackerTable]
    skipped: list[SkippedSheet]


# ---------------------------------------------------------------- reading a sheet


def is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


@cache
def reserved_words() -> frozenset[str]:
    rows = duckdb.sql("SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'").fetchall()
    return frozenset(r[0] for r in rows)


def slug(text: str) -> str:
    """A SQL name for a header: lower snake case, never starting with a digit nor a reserved word (End → end_)."""
    text = text.lower().replace("%", " pct ").replace(">", " gt ").replace("<", " lt ").replace("&", " and ")
    name = re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "column"
    if name[0].isdigit():
        return f"c_{name}"
    return f"{name}_" if name in reserved_words() else name


def column_letter(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


class _Sheet:
    """One worksheet split into titles, a header, body rows and notes."""

    def __init__(self, ws: Worksheet) -> None:
        self.name = ws.title
        self.grid: list[list[Any]] = [list(r) for r in ws.iter_rows(values_only=True)]
        width = max((len(r) for r in self.grid), default=0)
        self.grid = [r + [None] * (width - len(r)) for r in self.grid]
        self.merged = [(m.min_row - 1, m.max_row - 1, m.min_col - 1, m.max_col - 1) for m in ws.merged_cells.ranges]
        self.titles: list[str] = []
        self.notes: list[str] = []
        self.headers: list[str] = []
        self.body: list[list[Any]] = []
        self.first_body_row = 0
        self._split()

    def _filled(self, row: list[Any]) -> list[Any]:
        return [v for v in row if not is_blank(v)]

    def _text_row(self, row: list[Any]) -> str | None:
        """The text of a row holding one text cell (a title or note), unless it is a bare "Notes:" label."""
        filled = self._filled(row)
        if len(filled) == 1 and not is_formula(filled[0]):
            text = " ".join(str(filled[0]).split())
            return None if re.fullmatch(r"notes?\s*:?", text, re.IGNORECASE) else text
        return None

    def _split(self) -> None:
        header = next((i for i, r in enumerate(self.grid) if len(self._filled(r)) >= 2), None)
        if header is None:
            self.notes = [t for r in self.grid if (t := self._text_row(r))]
            return
        self.titles = [t for r in self.grid[:header] if (t := self._text_row(r))]
        on_header = [m for m in self.merged if m[0] == header]
        depth = max([m[1] - header + 1 for m in on_header] + [2 if any(m[3] > m[2] for m in on_header) else 1])
        self.headers = self._names(header, depth)
        start = header + depth
        end = next((i for i in range(start, len(self.grid)) if not self._filled(self.grid[i])), len(self.grid))
        self.body = self.grid[start:end]
        self.first_body_row = start
        self.notes = [t for r in self.grid[end:] if (t := self._text_row(r))]

    def _names(self, header: int, depth: int) -> list[str]:
        """One label per column: the header rows joined, a merged parent cell repeated over the columns it spans."""
        rows = [list(self.grid[header + d]) for d in range(depth)]
        for top, _, left, right in self.merged:
            if header <= top < header + depth:
                for c in range(left + 1, right + 1):
                    rows[top - header][c] = rows[top - header][left]
        labels = []
        for c in range(len(self.grid[header])):
            parts: list[str] = []
            for row in rows:
                part = " ".join(str(row[c]).split()) if not is_blank(row[c]) else ""
                if part and part not in parts:
                    parts.append(part)
            labels.append(" ".join(parts))
        return labels


# ---------------------------------------------------------------- cleaning


def text_date(value: str) -> date | None:
    for fmt in TEXT_DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _clean_text(value: Any) -> Any:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    if isinstance(value, datetime) and value.time() == datetime.min.time():
        return value.date()
    return value


def _column_type(values: list[Any]) -> tuple[ColumnType, int]:
    """The type of a column's values, and how many of them are dates typed as text."""
    present = [v for v in values if v is not None]
    if not present:
        return "VARCHAR", 0
    if all(isinstance(v, bool) for v in present):
        return "VARCHAR", 0
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return "BIGINT", 0
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return "DOUBLE", 0
    if all(isinstance(v, (date, datetime)) or (isinstance(v, str) and text_date(v)) for v in present):
        return "DATE", sum(isinstance(v, str) for v in present)
    return "VARCHAR", 0


def _convert(value: Any, kind: ColumnType) -> Any:
    if value is None:
        return None
    if kind == "DATE":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return text_date(str(value))
    if kind == "DOUBLE":
        return float(value)
    if kind == "VARCHAR":
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)
    return value


def in_column_names(formula: str, row: int, letters: dict[str, str]) -> str:
    """`formula` (on spreadsheet row `row`, 1-based) with references to its own row written as column names."""
    def name(m: re.Match[str]) -> str:
        letter, number = m.group(1), int(m.group(2))
        return letters.get(letter, m.group(0)) if number == row else m.group(0)

    shown = re.sub(r"(?<![A-Za-z0-9_!$'])\$?([A-Z]{1,3})\$?(\d+)(?![\d(!])", name, formula.lstrip("="))
    return shown if len(shown) <= FORMULA_SHOWN else shown[:FORMULA_SHOWN] + "…"


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


class _Table:
    """Rows of one or more sheets sharing a header, cleaned into typed columns."""

    def __init__(self, name: str, sheets: list[_Sheet]) -> None:
        self.name = name
        self.sheets = [s.name for s in sheets]
        headers = sheets[0].headers
        used = [c for c, h in enumerate(headers) if h or any(not is_blank(r[c]) for s in sheets for r in s.body)]
        names = _unique([slug(headers[c] or f"column {column_letter(c)}") for c in used])
        letters = {column_letter(c): n for c, n in zip(used, names, strict=True)}
        self.cleaning: list[str] = []

        derived = 0
        rows: list[tuple[str, int, list[Any]]] = []  # sheet, spreadsheet row (1-based), cells
        for sheet in sheets:
            for i, raw in enumerate(sheet.body):
                cells = [raw[c] for c in used]
                values = [v for v in cells[1:] if not is_blank(v)]
                if values and all(is_formula(v) for v in values):
                    derived += 1
                    continue
                rows.append((sheet.name, sheet.first_body_row + i + 1, cells))
        if derived:
            self.cleaning.append(f"{derived} row(s) of formulas only (totals) not loaded: sum the rows instead")

        self.formulas: list[FormulaColumn] = []
        kept: list[int] = []
        for k, c in enumerate(used):
            first = next(((row, cells[k]) for _, row, cells in rows if is_formula(cells[k])), None)
            if first is None:
                kept.append(k)
                continue
            row, formula = first
            self.formulas.append(FormulaColumn(
                name=names[k], header=headers[c], formula=in_column_names(str(formula), row, letters),
            ))

        self.columns: list[Column] = []
        self.multi = len(sheets) > 1
        cleaned = [[_clean_text(cells[k]) for k in kept] for _, _, cells in rows]
        typed: list[ColumnType] = []
        for j, k in enumerate(kept):
            kind, text_dates = _column_type([r[j] for r in cleaned])
            if text_dates:
                example = next(r[j] for r in cleaned if isinstance(r[j], str))
                self.cleaning.append(
                    f"{names[k]}: {text_dates} date(s) typed as text (e.g. {example!r}) read as day/month/year"
                )
            typed.append(kind)
            self.columns.append(Column(name=names[k], header=headers[used[k]], type=kind))
        self.rows = [
            ([sheet] if self.multi else []) + [_convert(v, t) for v, t in zip(r, typed, strict=True)]
            for (sheet, _, _), r in zip(rows, cleaned, strict=True)
        ]
        if self.multi:
            self.columns.insert(0, Column(name="sheet", header="(sheet name)", type="VARCHAR"))
            self.cleaning.append(f"one sheet per tab ({', '.join(self.sheets)}), combined; `sheet` names the tab")

    def model(self) -> TrackerTable:
        return TrackerTable(
            name=self.name, sheets=self.sheets, rows=len(self.rows), columns=self.columns, formulas=self.formulas,
            cleaning=self.cleaning,
        )


def _mostly_formulas(sheet: _Sheet) -> str | None:
    """A formula of the sheet when most of its filled body cells are formulas (a summary computed from other sheets)."""
    cells = [v for r in sheet.body for v in r if not is_blank(v)]
    formulas = [v for v in cells if is_formula(v)]
    if len(formulas) > len(cells) - len(formulas):
        return str(formulas[0])[:FORMULA_SHOWN]
    return None


def read_workbook(path: Path, rel_path: str) -> tuple[Workbook, list[_Table]]:
    wb = openpyxl.load_workbook(path)  # formulas as text: no saved values to read
    stem = slug(path.stem)
    sheets = [_Sheet(ws) for ws in wb.worksheets]
    titles: list[str] = []
    notes: list[str] = []
    skipped: list[SkippedSheet] = []
    groups: dict[tuple[str, ...], list[_Sheet]] = {}
    for sheet in sheets:
        titles += [f"{sheet.name}: {t}" for t in sheet.titles]
        notes += [f"{sheet.name}: {n}" for n in sheet.notes]
        if not sheet.body:
            skipped.append(SkippedSheet(sheet=sheet.name, reason="no table"))
            continue
        if formula := _mostly_formulas(sheet):
            skipped.append(SkippedSheet(
                sheet=sheet.name,
                reason=f"formulas without saved values (e.g. {formula}); compute the figures from the tables",
            ))
            continue
        groups.setdefault(tuple(sheet.headers), []).append(sheet)
    tables = [
        _Table(stem if len(group) > 1 else f"{stem}_{slug(group[0].name)}", group) for group in groups.values()
    ]
    workbook = Workbook(
        path=rel_path, titles=titles, notes=notes, tables=[t.model() for t in tables], skipped=skipped,
    )
    return workbook, tables


# ---------------------------------------------------------------- loading


def tracker_files(corpus_dir: Path) -> list[Path]:
    """The trackers of the corpus: its Excel workbooks, outside generator/ground-truth folders (`_...`)."""
    return sorted(
        p for p in corpus_dir.rglob("*.xlsx")
        if not any(part.startswith(("_", ".", "~$")) for part in p.relative_to(corpus_dir).parts)
    )


def load_trackers(corpus_dir: Path, db_path: Path, files: Sequence[Path] | None = None) -> list[Workbook]:
    """Clean the corpus's trackers into a fresh DuckDB database at `db_path` (replacing it). Returns what was loaded."""
    files = tracker_files(corpus_dir) if files is None else files
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(f".{db_path.name}.tmp")
    tmp.unlink(missing_ok=True)
    workbooks: list[Workbook] = []
    con = duckdb.connect(str(tmp))
    try:
        con.execute(f"CREATE TABLE {CATALOG_TABLE} (path VARCHAR PRIMARY KEY, spec JSON)")
        names: set[str] = set()
        for path in files:
            workbook, tables = read_workbook(path, path.relative_to(corpus_dir).as_posix())
            for table in tables:
                if table.name in names:
                    raise ValueError(f"Two trackers load into the table {table.name}")
                names.add(table.name)
                columns = ", ".join(f'"{c.name}" {c.type}' for c in table.columns)
                con.execute(f'CREATE TABLE "{table.name}" ({columns})')
                if table.rows:
                    marks = ", ".join("?" for _ in table.columns)
                    con.executemany(f'INSERT INTO "{table.name}" VALUES ({marks})', table.rows)
            con.execute(f"INSERT INTO {CATALOG_TABLE} VALUES (?, ?)", [workbook.path, workbook.model_dump_json()])
            workbooks.append(workbook)
    finally:
        con.close()
    os.replace(tmp, db_path)
    db_path.with_name(f".{db_path.name}.tmp.wal").unlink(missing_ok=True)
    return workbooks


def describe(workbooks: Sequence[Workbook], schema: str) -> str:
    """The trackers as the data agent reads them: tables (as `schema.table`), columns, notes and what was not loaded."""
    parts = []
    for wb in workbooks:
        lines = [f"{wb.path}"]
        lines += [f"  Title: {t}" for t in wb.titles]
        lines += [f"  Note: {n}" for n in wb.notes]
        for s in wb.skipped:
            lines.append(f"  Sheet {s.sheet} not loaded: {s.reason}.")
        for t in wb.tables:
            sheets = f"sheets {', '.join(t.sheets)}" if len(t.sheets) > 1 else f"sheet {t.sheets[0]}"
            cols = ", ".join(f"{c.name} {c.type}" for c in t.columns)
            lines.append(f"  - {schema}.{t.name} ({sheets}; {t.rows} rows): {cols}")
            for f in t.formulas:
                lines.append(f"    Not loaded, a formula without saved values: {f.name} ({f.header}) = {f.formula}")
            lines += [f"    Cleaning: {c}" for c in t.cleaning]
        parts.append("\n".join(lines))
    return "\n".join(parts)
