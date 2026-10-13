"""Load the PLG Records CSV export (poc-data/database) into a local LanceDB database.

LanceDB is embedded (no server): the "connection" is a folder path. It has no
foreign-key or primary-key enforcement, so the constraints declared in schema.sql
are (a) stored in the `_constraints` table, and (b) validated at load time, with
results stored in `_validation` and printed. Planned data-quality issues are kept,
not cleaned, because the POC must be tested against them.

Usage:
  .venv/bin/python poc-data/_generator/load_lancedb.py [--db poc-data/lancedb] [--overwrite]
"""
import argparse
import json
import os
import warnings
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

os.environ.setdefault("LANCE_LOG", "error")
warnings.filterwarnings("ignore", category=DeprecationWarning)

import lancedb  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.csv as pcsv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "database"

# Text columns that get a full-text-search index (free text a user would search).
FTS_COLUMNS = {
    "feedback_cases": ["description"],
    "inspections": ["remarks"],
    "applications": ["remarks"],
    "tasks": ["title"],
    "tenants": ["name"],
}
BITMAP_MAX_DISTINCT = 64  # low-cardinality columns get BITMAP, others BTREE


# ---------------------------------------------------------------- schema parse
def split_columns(body):
    parts, depth, cur = [], 0, ""
    for ch in body:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def arrow_type(sql_type):
    t = sql_type.upper()
    if m := re.match(r"NUMERIC\((\d+),(\d+)\)", t):
        return pa.decimal128(int(m[1]), int(m[2]))
    if t.startswith(("VARCHAR", "CHAR", "TEXT")):
        return pa.string()
    if t == "INT":
        return pa.int32()
    if t == "DATE":
        return pa.date32()
    if t == "BOOLEAN":
        return pa.bool_()
    raise ValueError(f"unmapped SQL type {sql_type}")


def parse_schema(sql):
    sql = re.sub(r"--[^\n]*", "", sql)
    tables, indexes = {}, []
    for name, body in re.findall(r"CREATE TABLE (\w+)\s*\((.*?)\);", sql, re.S):
        cols, pk, fks, checks, uniques, notnull = [], [], [], [], [], []
        for part in split_columns(body):
            if m := re.match(r"PRIMARY KEY\s*\(([^)]*)\)", part):
                pk = [c.strip() for c in m[1].split(",")]
                continue
            m = re.match(r"(\w+)\s+(\w+(?:\(\d+(?:,\d+)?\))?)(.*)", part, re.S)
            col, typ, rest = m[1], m[2], m[3]
            cols.append((col, typ, arrow_type(typ)))
            if "PRIMARY KEY" in rest:
                pk = [col]
            if "NOT NULL" in rest:
                notnull.append(col)
            if "UNIQUE" in rest:
                uniques.append(col)
            if r := re.search(r"REFERENCES (\w+)", rest):
                fks.append((col, r[1]))
            if c := re.search(r"CHECK\s*\(\w+ IN \((.*?)\)\)", rest):
                checks.append((col, re.findall(r"'([^']*)'", c[1])))
        tables[name] = dict(cols=cols, pk=pk, fks=fks, checks=checks, uniques=uniques, notnull=notnull)
    for ix, tbl, cols in re.findall(r"CREATE INDEX (\w+) ON (\w+)\(([^)]*)\);", sql):
        indexes.append((ix, tbl, [c.strip() for c in cols.split(",")]))
    # REFERENCES <table> with no column list targets that table's primary key
    for t in tables.values():
        t["fks"] = [(c, ref, tables[ref]["pk"][0]) for c, ref in t["fks"]]
    return tables, indexes


def load_order(tables):
    deps = {t: {ref for _, ref, _ in d["fks"] if ref != t} for t, d in tables.items()}
    q = deque(sorted(t for t, d in deps.items() if not d))
    order = []
    while q:
        t = q.popleft()
        order.append(t)
        for u in sorted(tables):
            if u not in order and u not in q and deps[u] <= set(order):
                q.append(u)
    assert len(order) == len(tables), "cyclic FKs"
    return order


# ---------------------------------------------------------------- load
def read_csv(path, spec):
    types = {c: at for c, _, at in spec["cols"]}
    tbl = pcsv.read_csv(
        path,
        convert_options=pcsv.ConvertOptions(
            column_types=types, true_values=["True"], false_values=["False"],
            null_values=[""], strings_can_be_null=True,
        ),
    )
    return tbl.select([c for c, _, _ in spec["cols"]])  # schema column order


def validate(name, spec, tbl, loaded):
    out = []

    def rec(kind, detail, n, sample=None):
        out.append(dict(table=name, check=kind, detail=detail, violations=int(n),
                        sample=json.dumps(sample or [])[:500]))

    pk = spec["pk"]
    keys = [tuple(r) for r in zip(*(tbl[c].to_pylist() for c in pk))]
    seen, dups = set(), []
    for k in keys:
        if k in seen:
            dups.append(k)
        seen.add(k)
    rec("PRIMARY KEY", f"({', '.join(pk)}) unique and not null", len(dups) + sum(None in k for k in keys),
        [list(k) for k in dups[:5]])
    for col in spec["notnull"]:
        rec("NOT NULL", col, tbl[col].null_count)
    for col in spec["uniques"]:
        vals = [v for v in tbl[col].to_pylist() if v is not None]
        d = sorted({v for v in vals if vals.count(v) > 1})
        rec("UNIQUE", col, len(vals) - len(set(vals)), d[:5])
    for col, allowed in spec["checks"]:
        bad = [v for v in tbl[col].to_pylist() if v is not None and v not in allowed]
        rec("CHECK", f"{col} IN {allowed}", len(bad), sorted(set(bad))[:5])
    for col, ref, refcol in spec["fks"]:
        parent = set(loaded[ref][refcol].to_pylist())
        orphans = [v for v in tbl[col].to_pylist() if v is not None and v not in parent]
        rec("FOREIGN KEY", f"{col} -> {ref}.{refcol}", len(orphans), sorted(set(orphans))[:5])
    return out


def build_indexes(t, name, spec, schema_indexes):
    made = []
    cols = list(spec["pk"]) + [c for c, _, _ in spec["fks"]]
    cols += [c for _, tbl, ix_cols in schema_indexes if tbl == name for c in ix_cols]
    cols += [c for c, _ in spec["checks"]]
    types = {c: at for c, _, at in spec["cols"]}
    for col in dict.fromkeys(cols):
        if pa.types.is_boolean(types[col]):
            continue
        distinct = len(pc.unique(t.to_arrow()[col]))
        low_card = distinct <= BITMAP_MAX_DISTINCT and col not in spec["pk"]
        kind = "BITMAP" if low_card and pa.types.is_string(types[col]) else "BTREE"
        t.create_scalar_index(col, index_type=kind, replace=True)
        made.append(dict(table=name, column=col, index_type=kind))
    for col in FTS_COLUMNS.get(name, []):
        t.create_fts_index(col, replace=True)
        made.append(dict(table=name, column=col, index_type="FTS"))
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "lancedb"))
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if db_path.exists() and any(db_path.iterdir()) and not args.overwrite:
        sys.exit(f"{db_path} already exists; pass --overwrite to rebuild it.")

    tables, schema_indexes = parse_schema((SRC / "schema.sql").read_text())
    db = lancedb.connect(str(db_path))
    loaded, validation, index_log, constraints = {}, [], [], []

    for name in load_order(tables):
        spec = tables[name]
        tbl = read_csv(SRC / f"{name}.csv", spec)
        validation += validate(name, spec, tbl, loaded)
        loaded[name] = tbl
        t = db.create_table(name, data=tbl, mode="overwrite")
        index_log += build_indexes(t, name, spec, schema_indexes)
        constraints.append(dict(table=name, kind="PRIMARY KEY", columns=",".join(spec["pk"]), ref_table=None, ref_columns=None, rule=None))
        constraints += [dict(table=name, kind="FOREIGN KEY", columns=c, ref_table=r, ref_columns=rc, rule=None) for c, r, rc in spec["fks"]]
        constraints += [dict(table=name, kind="CHECK", columns=c, ref_table=None, ref_columns=None, rule=f"IN {a}") for c, a in spec["checks"]]
        constraints += [dict(table=name, kind="UNIQUE", columns=c, ref_table=None, ref_columns=None, rule=None) for c in spec["uniques"]]
        constraints += [dict(table=name, kind="NOT NULL", columns=c, ref_table=None, ref_columns=None, rule=None) for c in spec["notnull"]]
        print(f"  {name:<22} {tbl.num_rows:>6} rows")

    db.create_table("_constraints", data=pa.Table.from_pylist(constraints), mode="overwrite")
    db.create_table("_validation", data=pa.Table.from_pylist(validation), mode="overwrite")
    db.create_table("_indexes", data=pa.Table.from_pylist(index_log), mode="overwrite")

    print(f"\nLoaded {len(tables)} tables, {sum(t.num_rows for t in loaded.values())} rows, {len(index_log)} indexes into {db_path}")
    print("Constraint violations (planned data-quality issues are expected):")
    for v in validation:
        if v["violations"]:
            print(f"  {v['table']}.{v['check']} {v['detail']}: {v['violations']}  e.g. {v['sample']}")


if __name__ == "__main__":
    main()
