"""Reproducible generator for the HEB PLG super-librarian POC corpus.

Usage:  python generate.py [--seed 42] [--out ..] [--overwrite]

Order of work: build master data -> register every artifact -> write _manifest.csv -> render artifacts
(emails last, because they attach other corpus files; SharePoint listing very last, because it hashes files)
-> dump _master/*.json (including ground truth for bundles, conflicts and data-quality issues).
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import master  # noqa: E402
from common import ARTS, iso, register  # noqa: E402
from c_comms import register_comms  # noqa: E402
from c_data import j_dump, register_data  # noqa: E402
from c_docs import register_docs  # noqa: E402
from c_pdfs import register_pdfs  # noqa: E402
from submissions import register_submissions  # noqa: E402

CORPUS_DIRS = ["emails", "docs", "docs/notes", "pdfs", "pdfs/submissions", "sheets", "exports", "decks", "database", "_master"]
FIELDS = ["id", "path", "type", "title", "author", "recipients", "date", "entities_referenced", "purpose", "test_questions", "flags"]
LIBRARY = {"docs": "Policies & SOPs", "pdfs": "Reports & Circulars", "sheets": "Reports - Data", "decks": "Presentations"}


def sharepoint_listing(M, root):
    items = []
    for a in ARTS:
        top = a["path"].split("/")[0]
        if top not in LIBRARY or a["id"] == "EXP-004":
            continue
        p = f"{root}/{a['path']}"
        with open(p, "rb") as f:
            data = f.read()
        lib = "Tenant Submissions" if "/submissions/" in a["path"] else LIBRARY[top]
        items.append(dict(itemId=f"SP-{int(hashlib.sha1(a['path'].encode()).hexdigest(), 16) % 10 ** 6:06d}", site="sites/PLG", library=lib,
                          serverRelativeUrl=f"/sites/PLG/{lib.replace(' ', '%20')}/{os.path.basename(a['path'])}", corpusPath=a["path"], title=a["title"],
                          modified=f"{a['date']}T09:00:00+08:00", modifiedBy=a["author"], sizeBytes=len(data), sha1=hashlib.sha1(data).hexdigest(),
                          contentType={"docx": "Document", "pdf": "Document", "xlsx": "Workbook", "pptx": "Presentation", "md": "Wiki Page", "txt": "Document"}.get(a["type"], "Document")))
    j_dump(f"{root}/exports/sharepoint_document_listing.json", dict(source="SharePoint (mock)", site="https://sharepoint.heb.example.org/sites/PLG",
                                                                     generated_at="2026-10-01T06:10:00+08:00", item_count=len(items), items=items))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--overwrite", action="store_true", help="allow writing into an out folder that already holds a corpus")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    if os.path.exists(os.path.join(out, "_manifest.csv")) and not args.overwrite:
        out = f"{out}-{dt.datetime.now():%Y%m%d-%H%M%S}"
        print(f"[!] corpus already exists; writing to new folder {out}")
    for d in CORPUS_DIRS:
        os.makedirs(os.path.join(out, d), exist_ok=True)

    M = master.build(args.seed)
    register_docs(M)
    register_pdfs(M)
    register_data(M)
    register_submissions(M)
    register_comms(M)
    register("EXP-004", "exports/sharepoint_document_listing.json", "json", "SharePoint document listing (PLG site)", "SharePoint", master.END,
             "Document library metadata with modified dates and hashes; drives incremental sync (changes_since)",
             "Which documents changed since 2026-08-01?", lambda root: sharepoint_listing(M, root))

    ids = [a["id"] for a in ARTS]
    assert len(ids) == len(set(ids)), "duplicate artifact ids"
    with open(os.path.join(out, "_manifest.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for a in sorted(ARTS, key=lambda a: a["id"]):
            w.writerow({k: a[k] for k in FIELDS})
    print(f"manifest: {len(ARTS)} artifacts")

    order = lambda a: (a["type"] == "eml", a["id"] == "EXP-004")  # noqa: E731
    for a in sorted(ARTS, key=order):
        os.makedirs(os.path.dirname(os.path.join(out, a["path"])), exist_ok=True)
        a["fn"](out)
    print("rendered all artifacts")

    md = os.path.join(out, "_master")
    for name in ["staff", "towns", "ncs", "blocks", "units", "tenants", "tenancies", "inspections", "feedback", "tickets", "applications", "tasks", "letters", "arrears"]:
        j_dump(f"{md}/{name}.json", M[name])
    j_dump(f"{md}/key_entities.json", M["key"])
    j_dump(f"{md}/planned_conflicts.json", M["conflicts"])
    j_dump(f"{md}/submission_bundles_ground_truth.json", M["bundles"])
    j_dump(f"{md}/data_quality_issues.json", M["data_quality"])
    j_dump(f"{md}/taxonomy_and_checklists.json", dict(taxonomy=M["taxonomy"], checklists=M["checklists"]))
    print(f"done -> {out}")


if __name__ == "__main__":
    main()
