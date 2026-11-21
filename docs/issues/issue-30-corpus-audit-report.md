# Issue #30: Corpus audit report

## What's been built

A policy owner runs `plg audit` and gets a report on the document library and PLG Records. They can read it under **Library → Audit findings** or fetch it with `GET /audit/reports/latest`.

The report has seven sections:

- **Conflicts.** Two documents, or a document and PLG Records, state different values for the same thing. Both sides are cited with a word-for-word quote, and the report gives the expected resolution and which side prevails.
- **Near-duplicates.** Found by MinHash and confirmed by document-vector similarity, then by Opus. The three planted pairs are SOP-011 v1.0/v1.1, the two commercial-tenant FAQs, and Circular 03/2026 as a PDF and as its `.txt` copy.
- **Stale documents.** SOPs that are older than the current version of the policy they implement, such as SOP-014 v1.2 against POL-003 v2.0.
- **Reports using superseded definitions.** For example, the QBR's 52 vacant units counts units under tender, which is `Vacant_v1`, while `Vacant_v2` applies from 15 Apr 2026.
- **Data rule violations.** Deterministic checks for overlapping tenancies, two current policy versions, a trade not allowed for its unit type, and duplicate tenants by BRN.
- **Gaps.** Questions from the new question log (`.plg/questions.jsonl`) that were answered "not covered", scored below `gap_min_score`, or rated 👎.
- **Dropped judgements.** Opus answers whose quotes could not be verified, or calls that failed.

Conflicts and duplicates between documents are written to the entity graph as `CONFLICTS_WITH` and `DUPLICATE_OF` edges between `LibraryDocument` nodes, through `GraphWriter`. The ontology moved these two slots from the abstract `Document` class to `LibraryDocument`, because FAQs, notes and decks are not Policy, SOP, Circular or Template nodes.

## How it contributes

The earlier issues let officers *ask* the library questions. This one lets policy owners *maintain* it. It points out where the corpus contradicts itself: C1–C5 are document against document, and C6 is a document against PLG Records. It also shows which copies to retire, which SOPs to revise after a policy change, and which reports quote a figure under an outdated definition. The gaps section shows which questions the library cannot answer yet. The graph edges let the knowledge agent and later checks use the conflicts the audit found.

## Module breakdown

| Path | New/Modified | Role |
|---|---|---|
| `src/plg/audit/candidates.py` | New | Deterministic candidates (no Claude): MinHash + LSH, document vectors, claim index, chunk similarity, lineage (stale SOPs), records (rent vs `tenancies`), superseded-definition chunks |
| `src/plg/audit/judge.py` | New | Opus judgements (`judge_pair`, `judge_duplicate`, `judge_definition`) with forced tools; quotes must be word for word or the item is dropped; PII masked |
| `src/plg/audit/rules.py` | New | Ontology rule checks over PLG Records (read-only) and index metadata |
| `src/plg/audit/questions.py` | New | `QuestionLog`: append-only, PII-masked log of answered turns |
| `src/plg/audit/gaps.py` | New | Gaps from the question log and the 👎 entries in the feedback log |
| `src/plg/audit/audit.py` | New | `run_audit`: candidates → judge → graph edges → rules → gaps → save |
| `src/plg/audit/model.py` | New | `AuditReport` and its parts; atomic save, newest report served |
| `ontology/plg.yaml`, `src/plg/ontology/generated/*` | Modified | `conflicts_with` / `duplicate_of` now run `LibraryDocument` → `LibraryDocument` |
| `src/plg/agents/runtime.py`, `agents/knowledge.py`, `graph/state.py` | Modified | Retrieval score carried to `Finding.top_score` |
| `src/plg/graph/build.py` | Modified | `merge` appends to the question log; skips flagged and clarification turns and never fails the run |
| `src/plg/config.py` | Modified | `audit_reports_dir`, `question_log`, `gap_min_score`, `audit_max_pairs`, `audit_duplicate_jaccard`, `audit_concurrency` |
| `src/plg/cli.py` | Modified | `plg audit` (same index lock as `plg sync`) |
| `src/plg/api/app.py` | Modified | `GET /audit/reports/latest`; passes the question log to the graph |
| `scripts/record_sse_fixtures.py` | Modified | `audit` scenario → `web/src/test/fixtures/audit_report.json` |
| `tests/test_audit_api.py`, `tests/conftest.py` | New/Modified | Candidate recall, CLI → API report, graph edges, dropped quotes, idempotence, rules, question log and gaps |
| `web/src/app/api/audit/reports/latest/route.ts` | New | BFF relay |
| `web/src/app/library/AuditFindings.tsx` (+ test) | New | Audit findings view |
| `web/src/app/library/LibraryScreen.tsx`, `library.module.css` | Modified | Categories / Audit findings tabs |
| `web/src/app/SourceViewer.tsx` | Modified | `QuoteViewer`: opens a chunk with the quote highlighted |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts`, `web/src/lib/events.ts`, `web/src/lib/server/plg-api.ts`, `web/src/test/sse.ts` | Modified | Regenerated types, report types, API client, fixture loader |

## Workflow map

```
plg ask / web ── plg-api ── graph: … → merge ──► QuestionLog (.plg/questions.jsonl)
                                         POST /feedback ──► FeedbackLog (.plg/feedback.jsonl)

plg audit (index lock)
  └─ run_audit
       ├─ candidates (SearchStore chunks + vectors, PLG Records, live Glossary)
       │    duplicates (MinHash/LSH + vectors) · conflict pairs (similarity + claims, lineage, records) · definition chunks · stale SOPs
       ├─ judge (LLMClient, Opus, node "audit") ── quotes verified against the shown chunks
       ├─ GraphWriter ──► CONFLICTS_WITH / DUPLICATE_OF between LibraryDocument nodes
       ├─ check_rules (PLG Records read-only, index metadata, vocab plg:trades)
       ├─ find_gaps (QuestionLog + FeedbackLog)
       └─ save ──► .plg/audit/<timestamp>.json

browser /library → Audit findings tab → BFF /api/audit/reports/latest → plg-api GET /audit/reports/latest → newest report
                   document side → QuoteViewer → /api/documents/{id}/chunks/{chunkId} (quote highlighted)
```

## Verification

- `uv run mypy`: clean. `uv run pytest`: 471 passed. `make ontology`: no drift.
- `web/`: typecheck, lint and build pass; `npm test` passes 186 tests.

## Known limits and next steps (from the code review)

- **Lineage:** stale SOPs and lineage pairs come from the index metadata only, not the entity graph. C5, the circular overriding a policy clause, is found by similarity, not by lineage.
- **C6:** the report covers C6 through the Internal Audit report. The scanned agreement vs PLG Records pair is checked at the candidate stage only, because the scan is usually not transcribed.
- **Gap threshold:** `gap_min_score` assumes Voyage rerank scores; the local cross-encoder uses a different scale.
- **Question log coverage:** only plg-api writes the question log, not `plg ask`.
- **`DUPLICATE_OF` direction:** for an earlier version, the edge runs from the current version to the old one; consider leaving those pairs to `SUPERSEDES`.
- **Access:** `GET /audit/reports/latest` is open to every signed-in officer, with no policy-owner check.
- **Weak citations:** a quote is checked for being word for word, not for containing the conflicting value. The scripted C1 quote is weak.
- **Live recall:** not measured yet. Run `plg audit` against the real index with Opus and compare with `planned_conflicts.json`.
- **Clean-ups:**
  - one shared Opus call helper in `judge.py`;
  - one shared "best score" function, instead of three;
  - the rule tests driven through `plg audit`;
  - `QuoteViewer` and `DocumentViewer` sharing their viewer states.
