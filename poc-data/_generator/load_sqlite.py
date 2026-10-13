"""Load the PLG Records CSV export (poc-data/database) into a SQLite database file.

The DDL in schema.sql is PostgreSQL-flavoured. It runs on SQLite after two type rewrites:
DATE -> TEXT (ISO-8601 strings; a DATE column would get NUMERIC affinity and compare
wrongly against string literals) and NUMERIC(p,s) -> REAL. A few extra lookup indexes
are added. Rows are loaded with foreign-key enforcement off (the
feedback_cases <-> iems_tickets references are circular), then checked with
PRAGMA foreign_key_check. Planned data-quality issues are kept, not cleaned, except
the duplicated payment row, which would violate the payments primary key: exact
duplicate rows are skipped and reported.

Usage:
  .venv/bin/python poc-data/_generator/load_sqlite.py [--db poc-data/plg_records.db] [--overwrite]
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "database"
DEFAULT_DB = ROOT / "plg_records.db"

# Parent tables first, so the load order also reads as the dependency order.
TABLE_ORDER = [
    "staff", "towns", "neighbourhood_centres", "blocks", "trades", "units", "tenants",
    "tenancies", "rent_invoices", "payments", "inspections", "feedback_cases",
    "iems_tickets", "applications", "application_documents", "tasks", "letters",
]

# Lookup paths the POC queries use that schema.sql does not index.
EXTRA_DDL = """
CREATE INDEX ix_tenants_brn ON tenants(brn);
CREATE INDEX ix_payments_tenancy ON payments(tenancy_id, paid_date);
CREATE INDEX ix_invoices_status ON rent_invoices(status, due_date);
CREATE INDEX ix_inspections_tenancy ON inspections(tenancy_id);
CREATE INDEX ix_inspections_officer ON inspections(officer_id, inspection_date);
CREATE INDEX ix_feedback_ticket ON feedback_cases(iems_ticket_id);
CREATE INDEX ix_feedback_status ON feedback_cases(status, reply_due);
CREATE INDEX ix_tickets_unit ON iems_tickets(unit_id, created_date);
CREATE INDEX ix_apps_unit ON applications(unit_id);
CREATE INDEX ix_apps_tenancy ON applications(tenancy_id);
CREATE INDEX ix_tasks_related ON tasks(related_id);
CREATE INDEX ix_letters_tenant ON letters(tenant_id, letter_date);
CREATE INDEX ix_letters_reference ON letters(reference_id);
CREATE INDEX ix_blocks_town ON blocks(town_code);
"""


def sqlite_ddl(sql):
    sql = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    sql = re.sub(r"\bDATE\b", "TEXT", sql)
    return re.sub(r"\bNUMERIC\(\d+,\s*\d+\)", "REAL", sql)


def column_types(conn, table):
    return {row[1]: row[2].upper() for row in conn.execute(f"PRAGMA table_info({table})")}


def converter(decl):
    if decl.startswith("INT"):
        return int
    if decl == "REAL":
        return float
    if decl == "BOOLEAN":
        return lambda v: {"true": 1, "false": 0}[v.strip().lower()]
    return str


def load_table(conn, table):
    types = column_types(conn, table)
    with open(SRC / f"{table}.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        convs = [converter(types[c]) for c in header]
        rows, seen, dupes = [], set(), []
        for raw in reader:
            if not raw:
                continue
            row = tuple(None if v == "" else conv(v) for v, conv in zip(raw, convs))
            if row in seen:
                dupes.append(row[0])
                continue
            seen.add(row)
            rows.append(row)
    cols = ", ".join(header)
    marks = ", ".join("?" * len(header))
    conn.executemany(f"INSERT INTO {table} ({cols}) VALUES ({marks})", rows)
    return len(rows), dupes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if args.db.exists():
        if not args.overwrite:
            sys.exit(f"{args.db} exists; pass --overwrite to rebuild it")
        args.db.unlink()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(sqlite_ddl((SRC / "schema.sql").read_text()))
    conn.executescript(EXTRA_DDL)

    csv_tables = {p.stem for p in SRC.glob("*.csv")}
    missing = set(TABLE_ORDER) ^ csv_tables
    if missing:
        sys.exit(f"table/CSV mismatch: {sorted(missing)}")

    print(f"Loading {SRC} -> {args.db}")
    with conn:
        for table in TABLE_ORDER:
            n, dupes = load_table(conn, table)
            note = f"  (skipped exact duplicate rows: {', '.join(dupes)})" if dupes else ""
            print(f"  {table:<24}{n:>7} rows{note}")

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        print(f"\nForeign-key violations: {len(violations)}")
        for table, rowid, parent, _ in violations[:20]:
            print(f"  {table} rowid={rowid} -> {parent}")
    else:
        print("\nForeign-key check: OK (0 violations)")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"Integrity check: {integrity}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.close()


if __name__ == "__main__":
    main()
