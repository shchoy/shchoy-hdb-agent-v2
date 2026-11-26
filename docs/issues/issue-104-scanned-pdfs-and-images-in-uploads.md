# Issue #104: scanned PDFs and images in uploads

Parent: #98 (uploads track). Built on #103 (text uploads into the officer's private library).

## What was built

Officers can now upload **scanned PDFs** (no text layer) and **images** (PNG/JPG) into their private library, as well as text documents.

- Claude transcribes each file **once**, using PDF input for scans and vision for images, always through `LLMClient`.
  - The transcript is saved by the file's content hash.
  - Uploading the same file again, opening it in the source viewer and locating a citation all reuse the saved transcript.
  - If the same file is uploaded twice at the same moment, the second upload waits for the first transcription.
- Files are refused **before any Claude call** when:
  - a scan has more than 100 pages;
  - a `.png`/`.jpg` file doesn't carry an image signature;
  - an image is over 3.75 MB, Claude's 5 MB vision limit once base64-encoded;
  - a PDF can't be opened.
- A file Claude can't read (no transcript, an empty transcript, or a failed call) is refused with **422 and a reason**. The composer's attachment chip already shows that reason.
- A scan's transcript is split into one section per page ("Page n"), so answers cite it **with page locations** (`p. n`). An image has no pages.
- The transcript is **screened for injection** like any upload. Planted spans are replaced by the ingestion marker, and the upload carries an `InjectionFlag`.
- On the web:
  - the file picker accepts `.png`, `.jpg` and `.jpeg`;
  - the source viewer shows an uploaded image's transcript and offers "Open original image" in a new tab.

## How it fits

Officers often hold paper: signed agreements, site notices and whiteboard photos. With this change those files become searchable, citable context in their private library, ranked together with the shared Library, exactly like a text upload. The shared index and the corpus transcripts (`plg sync`) are untouched.

## Modules

| Path | New/Modified | Role |
|---|---|---|
| `src/plg/ingest/scans.py` | Modified | Shared `transcribe(llm, path)` for PDFs and images, plus `media_block`. Adds `IMAGE_PROMPT`, `IMAGE_TYPES`, `SCAN_MAX_PAGES`, and `Transcript.parsed(paged=False)` for photos. `TranscriptStore.put` is now atomic. `ScanReader` uses `transcribe`. |
| `src/plg/uploads/library.py` | Modified | `add` is now async. Accepts images. Handles the scan and image path: signature, size and page checks, then a transcript read once (one lock per file hash) and saved in `<uploads_dir>/transcripts`. `_blocks` reads the saved transcript for the viewer. File writes run off the event loop. |
| `src/plg/documents.py` | Modified | Adds the `image` `DocumentKind` and `.png`/`.jpg`/`.jpeg` to `KINDS`. |
| `src/plg/api/app.py` | Modified | Passes the `LLMClient` to `UploadLibrary` and awaits `uploads.add`. Updates the 422 description. |
| `tests/test_uploads_api.py` | Modified | 13 new HTTP-seam tests for scans and images. |
| `web/src/app/uploads.ts` | Modified | `ACCEPT` now includes images. |
| `web/src/app/SourceViewer.tsx` (+ test) | Modified | Adds the "Open original image" link for `kind === "image"`. |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Regenerated | `DocumentKind` now includes `image`. |
| `web/src/test/fixtures/uploads/refused.json`, `Attachments.test.tsx` | Modified | Updated for the new list of accepted types. |

## Workflow

```
browser (paperclip / drop) → BFF /api/uploads → POST /uploads?filename=
  → UploadLibrary.add (type, size, space reservation; file written off-loop)
    → _read
        text-bearing file → extract
        scan PDF → page count ≤ 100 ─┐
        image → signature, ≤ 3.75 MB ┴→ _transcript (lock per hash)
              → TranscriptStore hit? → reuse
              → else scans.transcribe → LLMClient.complete(node ingest_scan, PDF/image block, forced record_transcript)
              → TranscriptStore.put
    → screened (injection marker) → chunks (scan: "Page n" sections) → LanceUploadIndex (owner-scoped)
  ← 201 Upload | 413/415/422 with a reason (shown on the chip)
question with attachments → knowledge → Searcher (UploadScope) → citation (upload: true, location "… (p. n)")
source viewer → /documents/{upload-…}[/chunks/…] → UploadLibrary.view/locate → saved transcript (never Claude)
```

## Next steps

- Excel uploads into a per-officer data catalog, and the "My documents" tab (other #98 tickets).
- Saved transcripts are not counted towards the officer's quota, and nothing removes them yet. Deleting from "My documents" should drop a transcript once no remaining upload has that file hash.
- A PDF with a text layer on only some pages is indexed from its text pages alone; its scanned pages are not transcribed.
- An e2e journey for uploading a photo.
