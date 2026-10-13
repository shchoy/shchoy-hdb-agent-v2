import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { startRun, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const runRequestSchema = z.object({ message: z.string().trim().min(1) });

/** Proxies a run to plg-api and streams its SSE body straight through, unbuffered. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const parsed = runRequestSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ detail: "message is required" }, { status: 400 });
  }
  const { id } = await params;

  let upstream: Response;
  try {
    // The browser disconnecting aborts the upstream run too.
    upstream = await startRun(staffId, id, { message: parsed.data.message }, request.signal);
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
