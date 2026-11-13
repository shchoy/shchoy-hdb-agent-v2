import { NextResponse, type NextRequest } from "next/server";
import { plgApiUnavailable, relaySse, resumeRun } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Re-attaches to a thread's latest run after a dropped connection or refresh; Last-Event-ID is forwarded. */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId)
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;

  let upstream: Response;
  try {
    upstream = await resumeRun(
      staffId,
      id,
      request.headers.get("last-event-id"),
      request.signal,
    );
  } catch {
    return plgApiUnavailable();
  }
  return relaySse(upstream);
}
