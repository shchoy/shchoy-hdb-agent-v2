import { NextResponse, type NextRequest } from "next/server";
import { cancelRun, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Stop generating: plg-api cancels the thread's running run; its refusals (404, 409) are relayed. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  let upstream: { status: number; body: unknown };
  try {
    upstream = await cancelRun(staffId, id);
  } catch {
    return plgApiUnavailable();
  }
  if (upstream.status === 204) return new Response(null, { status: 204 });
  return NextResponse.json(upstream.body, { status: upstream.status });
}
