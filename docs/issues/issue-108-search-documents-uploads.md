# Issue #108: Search Library documents and My uploads

Parent: #98 (organise, upload and search). Blocked by #107 (conversation search) and #103 (uploads), both done.

## What was built

The Ctrl/⌘K search dialog used to find only the officer's conversations. It now also has **Documents** and **My uploads** groups:

- **Keyword full-text only.** LanceDB full-text indexes on each chunk's `title` and `text` (2–3 character n-grams) supply candidates. Each candidate is then checked in Python: every searched word must start a word in its title or text. The search is prefix-based, so results appear as the officer types. No Claude or Voyage call is made.
- **One hit per document**, at its best chunk (the one whose text holds the most of the words). Each hit has:
  - a snippet with the matched words marked;
  - the match's span within that chunk's text.
- **Ranking:** current documents first, then documents whose title names every word, then the full-text score. Superseded versions carry `status: superseded` and show a **Superseded** badge.
- **Uploads are private.** They are searched in the officer's own upload index, filtered on the owner, so another officer never sees them. A renamed upload is found by its new title; a deleted one drops out.
- **Opening a result** shows the source viewer in a modal over the current screen, at the matching chunk with the match highlighted. A title-only match opens at the top of the document. Escape, the backdrop or Close returns focus to where search was opened.
- **One keyboard model for every group:** one listbox with a group per type. The arrows wrap across groups, and Enter or a click opens the result. The status line reads like "1 conversation, 2 documents and 1 upload found" or "Nothing matches “…”".
- **Renamed controls.** The dialog, its field and the sidebar button are now named "Search", since they cover more than conversations.

### Safety choices from the code review

- **plg-api never writes the shared Library index.** The keyword indexes are built by `plg sync`, in its optimize step. An index synced before #108 has none, so it finds no documents until the next sync.
- **Upload indexes are built after every write.** A pre-#108 uploads table gets its keyword indexes once, under the write lock. Searches don't take that lock otherwise.
- **Each group fails on its own.** Library and upload searches are best-effort: if one fails, it is logged and the other results still come back.

## How it contributes

This covers the documents and uploads part of #98's "Search" capability. Officers can find a policy, SOP or their own note by a phrase they remember and land on the exact passage, with no model cost or latency. The remaining scope is the approvals, audit and memory groups.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/search/keyword.py` | New | Keyword indexes (`build_indexes`, `indexed`) and `search()`: candidates → word-prefix check → `DocumentHit` (snippet, `MatchSpan`), ranking |
| `src/plg/search/lance.py` | Modified | `keyword_search(q)` on the Library chunks; `optimize()` builds the keyword indexes |
| `src/plg/search/store.py` | Modified | `SearchStore.keyword_search` in the protocol |
| `src/plg/uploads/index.py` | Modified | `keyword_search(owner, q)`; `_reindex` rebuilds every FTS index after add / remove / retitle |
| `src/plg/api/app.py` | Modified | `SearchResults.documents` / `.uploads`; `GET /search` runs the three searches in parallel, each document search best-effort |
| `tests/test_search_documents_api.py` | New | HTTP-seam tests over the synced corpus and uploads |
| `tests/conftest.py` | Modified | `make_api` defaults `search_db` to a temp folder (never `.plg/`) |
| `web/src/app/shell/SearchDialog.tsx` | Modified | Grouped results (Conversations, Documents, My uploads), document options, status summary |
| `web/src/app/shell/SourceDialog.tsx` | New | Modal holding the opened source |
| `web/src/app/SourceViewer.tsx` | Modified | `OpenedSource`: loads a document at once, located at a span |
| `web/src/app/shell/AppShell.tsx` | Modified | `reading` state, inert shell, focus return, Ctrl/⌘K from the source |
| `web/src/app/shell/shell.module.css` | Modified | Group and source dialog styles |
| `web/src/lib/events.ts`, `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Modified / generated | `DocumentHit` type |
| `web/src/app/shell/SearchDialog.test.tsx` | Modified | Groups, superseded badge, arrows across groups, open with highlight, upload, title match |
| `web/e2e/journeys.spec.ts`, `web/e2e/accessibility.spec.ts` | Modified | #108 journey (policy + own upload, other officer); renamed selectors |
| `CLAUDE.md`, `START.md` | Modified | Map, and the note that a sync builds the keyword indexes |

## Workflow

```
Ctrl/⌘K → SearchDialog ──GET /api/search?q (BFF, X-PLG-User)──► plg-api GET /search
                                                                 ├─ threads.search (SQLite FTS5)          → conversations
                                                                 ├─ index().keyword_search(q)              → documents
                                                                 │     LanceSearchStore → keyword.search(chunks table)
                                                                 └─ uploads.index.keyword_search(staff, q) → uploads
                                                                       LanceUploadIndex → keyword.search(uploads table, owner = staff)
choose a document/upload ─► AppShell.read(hit) ─► SourceDialog ─► OpenedSource
        GET /api/documents/{id}  +  GET /api/documents/{id}/chunks/{chunk}?start&end   (owner-checked for uploads)
        → Document view, scrolled to the <mark>ed match

plg sync ─► LanceSearchStore.optimize() ─► keyword.build_indexes(chunks)
POST/PATCH/DELETE /uploads ─► LanceUploadIndex._reindex() ─► keyword.build_indexes(uploads)
```

## Next steps

- Approvals, audit and memory result groups (the last search ticket under #98).
- Run `uv run plg sync` once on existing `.plg/lancedb` indexes so the Documents group finds results.
- The candidate pool is fixed at 500 chunks. That is plenty for the POC corpus (314 chunks), but a much larger corpus may need a bigger pool, or a word-prefix index if LanceDB gains one.
