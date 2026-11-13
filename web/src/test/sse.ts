import { readFileSync } from "node:fs";
import { join } from "node:path";
import { HttpResponse } from "msw";

/** A recorded plg-api SSE stream (see scripts/record_sse_fixtures.py at the repo root). */
export function fixture(name: "answer" | "not_covered" | "error" | "draft" | "policy_stance" | "data" | "multi_part" | "defect"): string {
  // Vitest runs from web/; import.meta.url is not a file URL under jsdom.
  return readFileSync(join(process.cwd(), "src/test/fixtures", `${name}.sse`), "utf8");
}

/** A recorded approvals response: `pending.json`, `audit.json` (parsed) or a resume stream `edit.sse` / `reject.sse` / `ticket_edit.sse`. */
export function approvalsFixture(name: "edit.sse" | "reject.sse" | "ticket_edit.sse"): string;
export function approvalsFixture(name: "pending.json" | "audit.json"): Record<string, unknown>[];
export function approvalsFixture(name: string): unknown {
  const raw = readFileSync(join(process.cwd(), "src/test/fixtures/approvals", name), "utf8");
  return name.endsWith(".json") ? JSON.parse(raw) : raw;
}

/**
 * Replays `body` as an SSE response in small chunks with a pause between them, so the
 * reader sees partial frames, split CRLFs and tokens arriving over time.
 */
export function sseResponse(body: string, chunkSize = 7): HttpResponse<ReadableStream> {
  const bytes = new TextEncoder().encode(body);
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) {
        controller.enqueue(bytes.slice(i, i + chunkSize));
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
      controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });
}
