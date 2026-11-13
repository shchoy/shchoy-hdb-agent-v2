/**
 * Run events streamed by plg-api as Server-Sent Events, validated with zod.
 *
 * The schemas are checked against the types generated from plg-api's OpenAPI document,
 * so a change to the back end's RunEvent fails `tsc` until this file is updated.
 */
import { z } from "zod";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type RunEvent = Schemas["RunEvent"];
export type CitationEvent = Schemas["CitationEvent"];
export type DraftEvent = Schemas["DraftEvent"];
export type PolicyStanceEvent = Schemas["PolicyStanceEvent"];
export type SqlTraceEvent = Schemas["SqlTraceEvent"];
export type ProposedActionEvent = Schemas["ProposedActionEvent"];
export type ClassificationEvent = Schemas["ClassificationEvent"];
export type DocCheckEvent = Schemas["DocCheckEvent"];
export type TasksEvent = Schemas["TasksEvent"];
export type TaskDigest = Schemas["TaskDigest"];
export type RankedTask = Schemas["RankedTask"];
export type Submission = Schemas["Submission"];
export type UserCtx = Schemas["UserCtx"];
export type ThreadSummary = Schemas["ThreadSummary"];
export type ThreadView = Schemas["ThreadView"];

/** A role for display, e.g. "estate_manager" → "estate manager". */
export function roleLabel(role: UserCtx["role"]): string {
  return role.replace("_", " ");
}

const seq = z.number().int();
const role = z.enum(["director", "manager", "estate_manager", "officer", "analyst", "legal"]);
const decision = z.enum(["approve", "edit", "reject"]);
const unfilledSlot = z.object({ slot: z.string(), reason: z.string() });
const piiFinding = z.object({
  kind: z.enum(["nric", "email", "phone", "tenant"]),
  slot: z.string(),
  message: z.string(),
});
const severity = z.enum(["Low", "Medium", "High", "Critical"]);
const docProblem = z.enum(["expired", "wrong_unit", "illegible_scan"]);
const candidate = z.object({ code: z.string(), category: z.string(), severity, confidence: z.number() });

export const runEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("node"),
    seq,
    node: z.string(),
    status: z.enum(["started", "finished"]),
  }),
  z.object({ type: z.literal("token"), seq, node: z.string(), text: z.string() }),
  z.object({
    type: z.literal("citation"),
    seq,
    index: z.number().int(),
    doc_id: z.string(),
    chunk_id: z.string(),
    title: z.string(),
    version: z.string().nullable(),
    location: z.string(),
    quote: z.string(),
    span: z.object({ start: z.number().int(), end: z.number().int() }),
  }),
  z.object({
    type: z.literal("sql_trace"),
    seq,
    plan: z.string(),
    sql: z.string(),
    as_of: z.string(),
    status: z.enum(["ok", "rejected"]),
    error: z.string().nullable(),
    result: z
      .object({
        columns: z.array(z.string()),
        row_count: z.number().int(),
        truncated: z.boolean(),
        rows: z.array(z.array(z.union([z.string(), z.number(), z.null()]))),
      })
      .nullable(),
    concepts: z.array(
      z.object({
        id: z.string(),
        concept: z.string(),
        version: z.number().int(),
        label: z.string(),
        effective_from: z.string().nullable(),
        effective_to: z.string().nullable(),
      }),
    ),
    warnings: z.array(z.string()),
    explanation: z.string(),
  }),
  z.object({
    type: z.literal("draft"),
    seq,
    draft_id: z.string(),
    template_id: z.string(),
    template_title: z.string(),
    template_version: z.string(),
    slots: z.record(z.string(), z.string()),
    unfilled: z.array(unfilledSlot),
    pii: z.array(piiFinding),
    html: z.string(),
  }),
  z.object({
    type: z.literal("policy_stance"),
    seq,
    policy_id: z.string(),
    title: z.string(),
    current: z.string().nullable(),
    versions: z.array(
      z.object({
        id: z.string(),
        label: z.string(),
        title: z.string(),
        version: z.string(),
        doc_id: z.string(),
        effective_from: z.string().nullable(),
        effective_to: z.string().nullable(),
        status: z.enum(["current", "superseded"]),
      }),
    ),
    supersessions: z.array(
      z.object({
        newer: z.string(),
        older: z.string(),
        evidence_chunk_id: z.string(),
        evidence_quote: z.string(),
      }),
    ),
    overrides: z.array(
      z.object({
        circular_id: z.string(),
        circular_title: z.string(),
        circular_doc_id: z.string(),
        clause_id: z.string(),
        clause_number: z.string(),
        policy_version: z.string(),
        effective_from: z.string().nullable(),
        effective_to: z.string().nullable(),
        scope: z.string().nullable(),
        evidence_chunk_id: z.string(),
        evidence_quote: z.string(),
      }),
    ),
  }),
  z.object({
    type: z.literal("classification"),
    seq,
    category_code: z.string(),
    category: z.string(),
    severity,
    team: z.string(),
    vendor: z.string().nullable(),
    is_defect: z.boolean(),
    sla_days: z.number().int().nullable(),
    confidence: z.number(),
    low_confidence: z.boolean(),
    rationale: z.string(),
    candidates: z.array(candidate),
  }),
  z.object({
    type: z.literal("doc_check"),
    seq,
    application_id: z.string(),
    app_type: z.string(),
    app_type_label: z.string(),
    tenant_id: z.string(),
    tenant_name: z.string(),
    unit_id: z.string(),
    unit_address: z.string(),
    submitted_date: z.string(),
    checklist: z.array(
      z.object({
        doc_code: z.string(),
        label: z.string(),
        description: z.string(),
        mandatory: z.boolean(),
        status: z.enum(["ok", "missing", "problem", "not_submitted"]),
        files: z.array(z.string()),
        problem: docProblem.nullable(),
        reason: z.string(),
      }),
    ),
    files: z.array(
      z.object({
        file: z.string(),
        doc_code: z.string().nullable(),
        doc_label: z.string().nullable(),
        read_by: z.enum(["text", "scan"]),
        problem: docProblem.nullable(),
        reason: z.string(),
      }),
    ),
    missing: z.array(z.string()),
    problems: z.record(z.string(), docProblem),
    complete: z.boolean(),
  }),
  z.object({
    type: z.literal("tasks"),
    seq,
    staff_id: z.string(),
    name: z.string(),
    title: z.string(),
    as_of: z.string(),
    open_count: z.number().int(),
    overdue_count: z.number().int(),
    tasks: z.array(
      z.object({
        task_id: z.string(),
        task_type: z.string(),
        title: z.string(),
        related_id: z.string(),
        due_date: z.string(),
        status: z.string(),
        safety_flag: z.boolean(),
        revenue_at_risk: z.number(),
        tenants_affected: z.number().int(),
        rank: z.number().int(),
        urgency: z.enum(["overdue", "this_week", "soon", "later"]),
        impact: z.enum(["high", "medium", "low"]),
        score: z.number().int(),
        overdue: z.boolean(),
        days_overdue: z.number().int(),
        reasons: z.array(z.string()),
      }),
    ),
  }),
  z.object({
    type: z.literal("proposed_action"),
    seq,
    action_id: z.string(),
    version: z.number().int(),
    action_type: z.enum(["send_letter", "raise_ticket"]),
    title: z.string(),
    payload: z.discriminatedUnion("kind", [
      z.object({
        kind: z.literal("letter"),
        draft_id: z.string(),
        template_id: z.string(),
        template_title: z.string(),
        template_version: z.string(),
        recipient: z.string(),
        slots: z.record(z.string(), z.string()),
        unfilled: z.array(unfilledSlot),
        pii: z.array(piiFinding),
      }),
      z.object({
        kind: z.literal("ticket"),
        feedback_id: z.string(),
        description: z.string(),
        unit_id: z.string().nullable(),
        category_code: z.string(),
        category: z.string(),
        severity,
        team: z.string(),
        vendor: z.string().nullable(),
        sla_days: z.number().int(),
        confidence: z.number(),
        low_confidence: z.boolean(),
        rationale: z.string(),
        candidates: z.array(candidate),
      }),
    ]),
    preview: z.string(),
    approver_roles: z.array(role),
    proposed_by: z.string(),
    proposed_at: z.string(),
    status: z.enum(["pending", "approved", "rejected"]),
  }),
  z.object({
    type: z.literal("interrupt"),
    seq,
    action_id: z.string(),
    version: z.number().int(),
    approver_roles: z.array(role),
  }),
  z.object({
    type: z.literal("action_result"),
    seq,
    action_id: z.string(),
    version: z.number().int(),
    decision,
    outbox_id: z.string().nullable(),
    ticket_id: z.string().nullable(),
  }),
  z.object({ type: z.literal("done"), seq, run_id: z.string() }),
  z.object({ type: z.literal("error"), seq, run_id: z.string(), message: z.string() }),
]);

type Parsed = z.infer<typeof runEventSchema>;
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
/** Compile-time drift check: fails `tsc` if the zod schema and the OpenAPI RunEvent differ. */
export type RunEventSchemaMatchesOpenApi = Same<Parsed, RunEvent> extends true ? true : never;
const runEventSchemaMatchesOpenApi: RunEventSchemaMatchesOpenApi = true;
void runEventSchemaMatchesOpenApi;

/** A frame that isn't a valid RunEvent. The run can't be trusted from that point on. */
export class InvalidFrameError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidFrameError";
  }
}

function toRunEvent(eventType: string, data: string): RunEvent {
  let json: unknown;
  try {
    json = JSON.parse(data);
  } catch {
    throw new InvalidFrameError("Frame data is not JSON");
  }
  const result = runEventSchema.safeParse(json);
  if (!result.success) throw new InvalidFrameError(`Frame is not a RunEvent: ${result.error.message}`);
  if (eventType && eventType !== result.data.type) {
    throw new InvalidFrameError(`Frame event "${eventType}" does not match type "${result.data.type}"`);
  }
  return result.data;
}

/**
 * Parses an SSE byte stream into validated RunEvents as they arrive.
 * Handles CR, LF and CRLF line endings, comment lines (heartbeats), multi-line data
 * and frames split anywhere across chunks. Throws InvalidFrameError on a bad frame.
 */
export async function* parseRunEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<RunEvent, void, undefined> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventType = "";
  let data: string[] = [];

  function* takeLines(final: boolean): Generator<string> {
    for (;;) {
      const match = /\r\n|\r|\n/.exec(buffer);
      if (!match) return;
      // A trailing CR may be the first half of a CRLF split across chunks.
      if (match[0] === "\r" && match.index === buffer.length - 1 && !final) return;
      const line = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      yield line;
    }
  }

  function* handle(line: string): Generator<RunEvent> {
    if (line === "") {
      if (data.length > 0) yield toRunEvent(eventType, data.join("\n"));
      eventType = "";
      data = [];
      return;
    }
    if (line.startsWith(":")) return;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") data.push(value);
    else if (field === "event") eventType = value;
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      for (const line of takeLines(done)) yield* handle(line);
      if (done) return;
    }
  } finally {
    // Stops the upstream body if the consumer gave up early or a frame was invalid.
    await reader.cancel().catch(() => undefined);
  }
}
