import { NextResponse, type NextRequest } from "next/server";
import { plgApiUnavailable, reorderGroups } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Reorder the officer's groups (#101): `{group_ids}` (every group, once, in the new order) is passed on; plg-api's
 * reordered groups or refusal (409: the groups changed since, e.g. in another browser) is relayed. */
export async function PUT(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const body: unknown = await request.json().catch(() => null);
  const ids = body && typeof body === "object" && "group_ids" in body ? body.group_ids : undefined;
  if (!Array.isArray(ids) || !ids.every((id) => typeof id === "string"))
    return NextResponse.json({ detail: "A list of group_ids is needed" }, { status: 422 });
  try {
    const upstream = await reorderGroups(staffId, ids);
    return NextResponse.json(upstream.body, { status: upstream.status });
  } catch {
    return plgApiUnavailable();
  }
}
