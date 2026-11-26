import { readFileSync } from "node:fs";
import { join } from "node:path";
import { HttpResponse } from "msw";
import type { AuditReport, Categorisation, MyDocuments, ThreadView, Upload } from "@/lib/events";

/** A recorded plg-api SSE stream (see scripts/record_sse_fixtures.py at the repo root). */
export function fixture(
  name:
    | "answer"
    | "not_covered"
    | "error"
    | "draft"
    | "policy_stance"
    | "data"
    | "multi_part"
    | "defect"
    | "doc_check"
    | "doc_check_problem"
    | "tasks"
    | "injection"
    | "injection_email"
    | "cancelled"
    | "upload",
): string {
  // Vitest runs from web/; import.meta.url is not a file URL under jsdom.
  return readFileSync(join(process.cwd(), "src/test/fixtures", `${name}.sse`), "utf8");
}

/** The recorded GET /submissions response: the applications the Document check screen offers. */
export function submissionsFixture(): Record<string, unknown>[] {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/submissions.json"), "utf8")) as Record<
    string,
    unknown
  >[];
}

/** The recorded GET /categories response: the Library's categories after `plg categorise` over the synced corpus. */
export function categoriesFixture(): Categorisation {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/categories.json"), "utf8")) as Categorisation;
}

/** A recorded task response: `digest.json` (S04's own), `digest_S06.json` (S04 viewing S06, limit 10), `team.json` (S04's team). */
export function tasksFixture(name: "digest.json" | "digest_S06.json"): Record<string, unknown>;
export function tasksFixture(name: "team.json"): Record<string, unknown>[];
export function tasksFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/tasks", name), "utf8"));
}

/**
 * A recorded approvals response: `pending.json`, `audit.json` (parsed) or a resume stream `edit.sse` / `reject.sse` /
 * `ticket_edit.sse`; `glossary_*`: a glossary change proposed by S02, in its term owner S08's inbox, approved by S08.
 */
export function approvalsFixture(name: "edit.sse" | "reject.sse" | "ticket_edit.sse" | "glossary_approve.sse"): string;
export function approvalsFixture(
  name: "pending.json" | "audit.json" | "glossary_pending.json" | "glossary_audit.json",
): Record<string, unknown>[];
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

/**
 * A recorded answer-feedback response: `thread.json` (S05's data answer with its turns), `receipt_up.json` (👍: an SQL
 * example proposed), `receipt_down.json` (👎 with a correction and a team fact), `curation.json` (S03's curator queue: all
 * three proposed by S05), `decided.json` (S03 approving the team fact).
 */
export function feedbackFixture(name: "curation.json"): Record<string, unknown>[];
export function feedbackFixture(
  name: "thread.json" | "receipt_up.json" | "receipt_down.json" | "decided.json",
): Record<string, unknown>;
export function feedbackFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/feedback", name), "utf8"));
}

/** The recorded GET /audit/reports/latest response: the corpus audit report over the synced corpus. */
export function auditReportFixture(): AuditReport {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/audit_report.json"), "utf8")) as AuditReport;
}

/** The recorded POST /uploads response (#103): the officer's site-visit note in their private library. */
export function uploadFixture(): Upload {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/uploads/upload.json"), "utf8")) as Upload;
}

/** A recorded refused upload (415, an unsupported type): plg-api's status and body. */
export function uploadRefusedFixture(): { status: number; body: { detail: string } } {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/uploads/refused.json"), "utf8")) as {
    status: number;
    body: { detail: string };
  };
}

/**
 * Recorded Library → My documents responses (#106): `my_documents.json` (GET /my-documents: a handover checklist and
 * the site-visit note, the note used in one conversation), `thread_removed.json` (GET /threads/{id} of that conversation
 * once the note was deleted: its citation is `removed`).
 */
export function myDocumentsFixture(name: "my_documents.json"): MyDocuments;
export function myDocumentsFixture(name: "thread_removed.json"): ThreadView;
export function myDocumentsFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(process.cwd(), "src/test/fixtures/uploads", name), "utf8"));
}
