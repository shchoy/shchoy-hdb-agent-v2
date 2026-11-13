import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { plgApiUnavailable, resumeThread } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const decisionSchema = z.object({
  action_id: z.string().min(1),
  version: z.number().int(),
  decision: z.enum(["approve", "edit", "reject"]),
  edits: z.record(z.string(), z.string()).default({}),
  reason: z.string().default(""),
});

/**
 * The officer's decision on a pending action. plg-api checks it (owner, role, exact version, reason, slots);
 * a refusal is relayed with its reason, and the resumed run's SSE body is streamed straight through.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const parsed = decisionSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ detail: "Not a decision on an action" }, { status: 400 });
  const { id } = await params;

  let upstream: Response;
  try {
    // Not tied to the browser request: a decision, once made, is carried out even if the page is closed.
    upstream = await resumeThread(staffId, id, parsed.data);
  } catch {
    return plgApiUnavailable();
  }
  if (upstream.status !== 200 || !upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
