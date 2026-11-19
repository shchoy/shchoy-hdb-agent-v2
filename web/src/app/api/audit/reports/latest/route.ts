import { NextResponse, type NextRequest } from "next/server";
import { getLatestAuditReport, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** The latest corpus audit report; plg-api's 404 (no audit has run yet) and refusals are relayed. */
export async function GET(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  try {
    const { status, body } = await getLatestAuditReport(staffId);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
