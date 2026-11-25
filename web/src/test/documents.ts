import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { components } from "@/lib/api/schema";

export type DocumentView = components["schemas"]["DocumentView"];
export type ChunkLocation = components["schemas"]["ChunkLocation"];
export type DocumentKind = DocumentView["kind"];

/** A recorded plg-api document and the location of one cited span in it (scripts/record_sse_fixtures.py). */
export type DocumentFixture = { document: DocumentView; location: ChunkLocation; start: number; end: number };

/** `upload`: the officer's own site-visit note (#103), as its citation in upload.sse asks for it. */
export function documentFixture(kind: "pdf" | "docx" | "email" | "markdown" | "upload"): DocumentFixture {
  return JSON.parse(
    readFileSync(join(process.cwd(), "src/test/fixtures/documents", `${kind}.json`), "utf8"),
  ) as DocumentFixture;
}
