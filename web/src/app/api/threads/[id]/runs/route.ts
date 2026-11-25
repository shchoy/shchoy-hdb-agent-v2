import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { startRun, plgApiUnavailable, relaySse } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** `attachments`: the officer's uploads sent with the question (#103); plg-api checks they are theirs and how many. */
const runRequestSchema = z.object({
  message: z.string().trim().min(1),
  attachments: z.array(z.string().min(1)).optional(),
});

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
    const { message, attachments } = parsed.data;
    upstream = await startRun(staffId, id, { message, ...(attachments?.length ? { attachments } : {}) }, request.signal);
  } catch {
    return plgApiUnavailable();
  }

  return relaySse(upstream);
}
