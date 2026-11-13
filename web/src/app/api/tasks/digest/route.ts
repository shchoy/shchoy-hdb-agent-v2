import { NextResponse, type NextRequest } from "next/server";
import { getTaskDigest, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * An officer's top open tasks, ranked (default: the signed-in officer's own). Forwards `staff_id` and `limit`;
 * plg-api's refusals (403 another officer's tasks, 404 unknown officer, 422 bad limit) are relayed.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const params = request.nextUrl.searchParams;
  const query: { staff_id?: string; limit?: number } = {};
  const officer = params.get("staff_id");
  if (officer) query.staff_id = officer;
  const limit = params.get("limit");
  if (limit !== null) {
    if (!/^\d+$/.test(limit)) return NextResponse.json({ detail: "limit must be a whole number" }, { status: 422 });
    query.limit = Number(limit);
  }
  try {
    const { status, body } = await getTaskDigest(staffId, query);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
