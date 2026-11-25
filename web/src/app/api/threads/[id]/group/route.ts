import { NextResponse, type NextRequest } from "next/server";
import { moveThread, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/** Move a conversation: `{group_id}` (a group's ID, or null for Recent) is passed on; plg-api's ThreadSummary or
 * refusal (404 thread or group not found) is relayed. */
export async function PUT(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  const body: unknown = await request.json().catch(() => null);
  const groupId = body && typeof body === "object" && "group_id" in body ? body.group_id : undefined;
  if (typeof groupId !== "string" && groupId !== null)
    return NextResponse.json({ detail: "A group_id (or null) is needed" }, { status: 422 });
  try {
    const upstream = await moveThread(staffId, id, groupId);
    return NextResponse.json(upstream.body, { status: upstream.status });
  } catch {
    return plgApiUnavailable();
  }
}
