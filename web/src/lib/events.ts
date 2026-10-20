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
export type UserCtx = Schemas["UserCtx"];

/** A role for display, e.g. "estate_manager" → "estate manager". */
export function roleLabel(role: UserCtx["role"]): string {
  return role.replace("_", " ");
}

const seq = z.number().int();

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
        sample: z.array(z.array(z.union([z.string(), z.number(), z.null()]))),
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
    unfilled: z.array(z.object({ slot: z.string(), reason: z.string() })),
    pii: z.array(z.object({ kind: z.string(), slot: z.string(), message: z.string() })),
    html: z.string(),
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
