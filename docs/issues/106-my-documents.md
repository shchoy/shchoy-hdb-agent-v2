# Issue #106: Library → My documents tab

## What was built

Library now has a third tab, **My documents**, where officers manage their private uploads (#103/#104).

- Each upload is a card showing its name, type, file name, size, upload date and the conversations that used it. A meter at the top shows space used against the 200 MB cap.
- **Upload files** adds documents without a conversation. It shows progress, and a refused file gets an alert with the reason.
- Each card has three actions:
  - **Open** shows the upload in the source viewer.
  - **Rename** edits the name inline: Enter saves, Escape cancels.
  - **Delete** asks for confirmation inline first.
- Deleting an upload:
  - takes it out of every later search;
  - frees its space;
  - makes it 404 everywhere;
  - removes its saved scan transcript, unless another upload is the same file.
- Answers that cited a deleted upload keep the citation, marked **Removed**, and have no "Open source" button.
- Deleting a conversation keeps its uploads. The conversation simply drops out of the upload's "Used in" list.
- The per-officer data catalog (#105, Excel uploads) does not exist yet. Delete has nothing to remove there until it does.

## How it fits the project

The spec (#98) makes uploads the officer's private library, and they outlive conversations. This tab is where that library is managed:

- Officers can see what they hold and how much space it uses, and free space when needed.
- They can rename a file so it reads better in citations.
- Deleting an upload keeps answers honest: an old answer shows its source as gone, rather than linking to a 404.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/uploads/library.py` | modified | `rename`, `delete`, `quota_bytes`; atomic `upload.json` writes; checks whether another upload holds the same file |
| `src/plg/uploads/index.py` | modified | `remove(owner, doc_id)` (filtered by owner, FTS index rebuilt), `retitle` (title and header rewritten, vectors kept) |
| `src/plg/ingest/scans.py` | modified | `TranscriptStore.remove_digest` |
| `src/plg/threads.py` | modified | `plg_upload_uses` table: `record_uses`, `uses(staff)`, `forget_upload`; deleting a thread drops its rows; `RunRegistry.start(observe=)` |
| `src/plg/feedback/model.py` | modified | `NumberedCitation.removed` |
| `src/plg/api/app.py` | modified | `GET /my-documents`, `PATCH/DELETE /uploads/{id}`; records uses on attach and on upload citations; `GET /threads/{id}` marks removed citations |
| `tests/test_my_documents_api.py` | new | HTTP-seam tests (10) |
| `web/src/app/api/my-documents/route.ts`, `web/src/app/api/uploads/[id]/route.ts` | new | BFF relays (+ route tests) |
| `web/src/lib/server/plg-api.ts` | modified | `getMyDocuments`, `renameUpload`, `deleteUpload` |
| `web/src/app/library/MyDocuments.tsx` (+ test) | new | The tab |
| `web/src/app/library/LibraryScreen.tsx`, `library.module.css` | modified | Third tab, styles (tokens only) |
| `web/src/app/SourcesPanel.tsx`, `SourceViewer.tsx`, `src/lib/events.ts` | modified | Removed state; message when a deleted upload returns 404; `removed` defaults to false |
| `scripts/record_sse_fixtures.py`, `web/src/test/fixtures/uploads/*.json` | modified / new | `my_documents` scenario |
| `web/e2e/accessibility.spec.ts`, `web/e2e/journeys.spec.ts` | modified | Phone fit and axe checks in both themes; upload, rename and delete journeys; removed citation |

## Workflow

```
Library → My documents ──GET /api/my-documents──▶ BFF ──▶ GET /my-documents
                                                      ├─ UploadLibrary.of(staff)            (upload.json files)
                                                      └─ ThreadStore.uses(staff)            (plg_upload_uses ⨝ plg_threads)
Upload files ──POST /api/uploads──▶ POST /uploads ──▶ UploadLibrary.add (screen, chunk, index)
Rename ──PATCH /api/uploads/{id}──▶ UploadLibrary.rename ──▶ upload.json + LanceUploadIndex.retitle
Delete ──DELETE /api/uploads/{id}──▶ UploadLibrary.delete ──▶ index rows → folder → transcript (if unshared)
                                   └▶ ThreadStore.forget_upload
Ask with attachments ──POST /threads/{id}/runs──▶ record_uses(attached); RunRegistry observe: upload citation → record_uses
Reopen conversation ──GET /threads/{id}──▶ turns' upload citations whose upload is gone → removed=true ──▶ SourcesPanel "Removed"
```

## Next steps

- #105 (Excel uploads → per-officer catalog): `UploadLibrary.delete` must also drop the officer's tables.
- Uses are recorded only from now on. Uploads attached or cited before this change show no conversations.
- An answer already on screen when its upload is deleted in another tab is not re-marked. Opening it shows the "deleted" message.
