# Issue #7 — Source viewer with cited-span highlight

Parent: #1 · Blocked by: #6 (policy Q&A with citations)

## What was built

A PLG officer opens a citation chip's **Open source** button and sees the cited document in place, with the cited span
highlighted (`<mark>`), for PDF, DOCX, email and Markdown (PPTX and plain text work the same way).

- **API** (`plg-api`, all need `X-PLG-User`):
  - `GET /documents/{doc_id}` — the file as plain text blocks (`text`, `level`, `page`) plus kind, filename, content type.
  - `GET /documents/{doc_id}/file` — the source file; PDFs inline, everything else an attachment; `nosniff` and CSP `sandbox`.
  - `GET /documents/{doc_id}/chunks/{chunk_id}?start&end` — where the span (offsets in the chunk text, as in a citation) sits:
    quote, page and block highlights. Without a span, the whole chunk.
- **BFF** relays all three under `/api/documents/...` with the session cookie's staff ID; the file route passes only an allow-list of headers.
- **Web**: `SourceViewer` fetches the document and the span location, renders blocks as React text with `<mark>`s, groups PDFs
  by page and links to the original PDF at the cited page (other types: download link). If the quote can't be found in the
  file any more, it shows the quote in a note instead.
- **No raw HTML ever renders**: block text is only ever text nodes, so a `<script>` in an email is shown as inert characters.
  Path traversal is blocked (`source_path` must resolve inside `corpus_dir`).

## Module map

| Path | Role |
|---|---|
| `src/plg/documents.py` | `DocumentLibrary` (view / file / locate), response models `DocumentView`, `ChunkLocation`, `Highlight` |
| `src/plg/api/app.py` | Three new routes; `create_app(..., store=)` |
| `tests/test_documents_api.py` | HTTP-seam tests per file type, traversal, auth, 404s |
| `web/src/app/SourceViewer.tsx` (+ test) | The viewer, per-type component tests on recorded responses |
| `web/src/app/api/documents/**` (+ `routes.test.ts`) | BFF routes |
| `web/src/lib/server/plg-api.ts` | `getDocument`, `getChunkLocation`, `getDocumentFile` |
| `scripts/record_sse_fixtures.py` | Also records `web/src/test/fixtures/documents/*.json` |
| `web/openapi.json`, `src/lib/api/schema.d.ts` | Regenerated |

## Decisions and known limits

- PDFs are shown as extracted text by page with the highlight (no pdf.js); the original opens in a new tab at the cited page, unhighlighted.
- DOCX/Markdown are shown as text blocks (headings bolded), not fully styled; emails with an HTML body show the tags as text.
- Any signed-in user can read any indexed document (no per-document access control yet).
- The viewer lives inside each citation chip rather than a separate Sources panel.
- Files are re-parsed per request (no cache).

## Next steps

- Per-document access control; caching of parsed documents.
- Optional: real PDF rendering with highlight (pdf.js), richer DOCX/Markdown rendering behind a sanitiser.
- Review nits not done: share BFF route scaffolding, a `Span` type, a `SourceFile.inline` flag.
