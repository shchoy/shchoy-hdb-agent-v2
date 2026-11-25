# Issue #103: Upload a text document into the conversation

Parent: #98 (Conversation workspace: uploads, groups, pins and search). This is the first ticket of the uploads track.

## What was built

Officers can now give the agent their own documents as context:

- **Attaching files.** The Ask screen's composer has a paperclip button ("Attach files"), and files can also be dropped anywhere on the screen. Each file becomes a chip above the composer showing its name, its size and real upload progress (XHR). The chip then shows Ready, or the server's refusal as an alert. A chip can be removed (this aborts an upload still in flight). At most 5 files go with one question, and Ask is disabled while a file is still uploading.
- **The officer's private library.** `POST /uploads` stores each file under `.plg/uploads/<staff ID>/<upload ID>/` and indexes it in its own LanceDB table (`.plg/uploads/index`), with every row carrying its owner. The shared Library index is never written to.
- **Supported types.** Text-layer PDF, DOCX, TXT, MD and EML. Anything else is refused with 415. A PDF without a text layer (a scan) and an unreadable file are refused with 422.
- **Limits, enforced on the server.**
  - 20 MB per file: the request body is read only until it passes the limit, then 413.
  - 200 MB per officer: 413. The space is reserved under a lock, so uploads sent at the same time can't overrun it.
  - 5 files per question: 422 on the run request.
  - An attachment ID that isn't the caller's own upload gets 404.
- **Prompt-injection screening.** Every block of an upload goes through the rule-based injection rules, as emails do at ingestion. Flagged spans are replaced by the ingestion marker before chunking.
  - The upload response carries an `InjectionFlag`. The chip shows "Instructions removed" and an `InjectionAlert` straight away.
  - When the knowledge agent later reads the upload, it gets the usual injection note and an `injection` event is streamed.
- **Search and citations.**
  - Every knowledge search now covers the shared corpus plus the asker's own uploads. Both sets of candidates are reranked together.
  - Files attached to the current question are boosted: their best passages always keep up to half of the result places.
  - The knowledge agent is told which files were attached.
  - A question sent with files always reaches the knowledge agent.
  - Citations from an upload carry `upload: true`. The web app names the `[n]` marker "…, your upload" and shows a "Your upload" badge in the sources panel and the source viewer, with the cited span highlighted.
- **Privacy.** An upload is visible only to its owner. Another officer never gets it in search results or citations, and gets 404 from `/documents/{id}`, `/file` and `/chunks/…`. `GET /uploads` lists only the caller's own uploads.
- **Tracing.** Upload passages reach LangSmith only through the traced search, which uses the masking `tracing_client`. A test checks that an NRIC and a phone number in an upload are masked.

## How it fits the project

Until now the Super-Librarian answered only from the shared corpus that `plg sync` indexes. With uploads, an officer can ask about their own material (site notes, letters from tenants, forwarded emails) next to PLG policy, still with exact citations. The existing guardrails apply unchanged: the same injection rules, PII masking in traces, and per-officer isolation like memory. This also lays the base for the rest of the track: scans and images (Claude transcription), Excel (a per-officer data catalog) and the My documents tab.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/uploads/library.py` | New | `UploadLibrary`: validate type, size and space; store; screen; chunk; embed; index; `of`/`get`/`view`/`file`/`locate` for the owner; `scope()` returns an `UploadScope` |
| `src/plg/uploads/index.py` | New | `LanceUploadIndex`: its own `uploads` table (chunk schema + owner), owner-filtered hybrid search, serialised writes |
| `src/plg/search/rerank.py` | Modified | `PrivateIndex` and `UploadScope`; `Searcher.search(..., uploads=)` reranks upload and Library candidates together; `boosted`; trace inputs record only the owner |
| `src/plg/search/models.py` | Modified | Adds `source_system` value `"upload"` |
| `src/plg/agents/knowledge.py` | Modified | Search tool passes the scope; titles uploads "(Your upload)"; names the attached files in the agent's context; a system prompt rule for uploads |
| `src/plg/agents/runtime.py` | Modified | `Citation.upload` |
| `src/plg/documents.py` | Modified | `DocumentView.upload`; `KINDS` and `highlights_of` made public for reuse |
| `src/plg/ingest/sync.py` | Modified | `screened()` made public: the same screening for emails and uploads |
| `src/plg/graph/state.py`, `graph/build.py` | Modified | `attachments` in state; route sends to knowledge when files are attached; knowledge node builds the officer's scope |
| `src/plg/runs.py`, `src/plg/threads.py` | Modified | Pass `attachments` from the run request into the graph input (and the trace inputs) |
| `src/plg/api/app.py` | Modified | `POST`/`GET /uploads`; `RunRequest.attachments` (422 / 404); owner-checked upload document endpoints; `create_app(embedder=)` |
| `src/plg/config.py` | Modified | `uploads_dir`, `upload_max_bytes`, `upload_max_files`, `upload_quota_bytes` |
| `tests/test_uploads_api.py` | New | HTTP-seam tests (22) |
| `scripts/record_sse_fixtures.py`, `scripts/e2e_server.py` | Modified | `upload` scenario and fixtures; uploads kept in scratch dirs with an offline embedder; the e2e upload question |
| `web/src/app/api/uploads/route.ts` | New | BFF: streams the file to plg-api, relays refusals, lists uploads |
| `web/src/lib/server/plg-api.ts`, `api/threads/[id]/runs/route.ts` | Modified | `uploadFile`/`listUploads`; the runs relay passes `attachments` through |
| `web/src/app/uploads.ts` | New | Accepted types, `MAX_ATTACHMENTS`, `formatSize`, XHR `uploadFile` with progress and abort |
| `web/src/app/Attachments.tsx` | New | `useAttachments` hook and `AttachmentChips` (progress, Ready, refusal, injection alert, remove), paperclip icon |
| `web/src/app/AskScreen.tsx`, `runClient.ts`, `ask.module.css` | Modified | Paperclip, file drop target, sending attachments, files listed in the question bubble |
| `web/src/app/AnswerText.tsx`, `SourcesPanel.tsx`, `SourceViewer.tsx` | Modified | "Your upload" marking on the marker, sources panel and viewer |
| `web/src/lib/events.ts`, `openapi.json`, `schema.d.ts` | Modified / generated | `citation.upload` (defaults to false), the `Upload` type |
| `web/e2e/journeys.spec.ts`, `accessibility.spec.ts`, `helpers.ts` | Modified | Upload journey; axe checks of the composer with chips (light, dark, phone) |

## Workflow

```
Browser (Ask screen)
  paperclip / drop ──► uploads.ts XHR POST /api/uploads?filename=  (progress → chip)
                          │  BFF route.ts (adds X-PLG-User, streams body)
                          ▼
                    plg-api POST /uploads ──► UploadLibrary.add
                          size/type/space checks ─► 413/415/422
                          extract ─► screened (injection marker) ─► chunk ─► embed
                          ─► LanceUploadIndex (owner column)   + file & upload.json
                          ◄── Upload {upload_id, injection?}  → chip Ready (+ InjectionAlert)

  Ask ──► POST /api/threads/{id}/runs {message, attachments}
            ▼
       plg-api create_run (≤5, own uploads) ─► RunRegistry.start ─► stream_run (state.attachments)
            ▼
       graph: route (+knowledge when attached) ─► knowledge_node
            UploadLibrary.scope(owner, attached) ─► knowledge.answer(uploads, attached)
            search_corpus ─► Searcher.search(uploads=scope)
                 Library LanceSearchStore candidates + LanceUploadIndex(owner) candidates
                 ─► rerank together ─► boosted (attached files kept) ─► _guarded (injection note/event)
            ◄── citations (upload: true) ─► merge ─► SSE citation/injection/token events
            ▼
  Answer: [n] "…, your upload" ─► SourcesPanel badge ─► SourceViewer
            GET /api/documents/{upload-…}[/chunks/…]  (owner only, else 404; span highlighted)
```

## Next steps

- Scanned PDFs and images (Claude transcription, saved once), Excel uploads (a per-officer data catalog), and the Library's **My documents** tab (list, rename, delete, space used). `GET /uploads` is already there for that tab.
- The question bubble lists the attached files only for the live turn; history doesn't record them yet.
- Searches the agent narrows with `doc_types` leave uploads out (they have `doc_type "upload"`).
