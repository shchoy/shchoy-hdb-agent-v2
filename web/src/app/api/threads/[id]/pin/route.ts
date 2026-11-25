import { NextResponse, type NextRequest } from "next/server";
import { pinThread, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/** Pin or unpin a conversation (#102): `{pinned}` (a boolean) is passed on; plg-api's reply or refusal (404) is relayed. */
export async function PUT(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  const body: unknown = await request.json().catch(() => null);
  const pinned = body && typeof body === "object" && "pinned" in body ? body.pinned : undefined;
  if (typeof pinned !== "boolean") return NextResponse.json({ detail: "pinned (true or false) is needed" }, { status: 422 });
  try {
    const upstream = await pinThread(staffId, id, pinned);
    return NextResponse.json(upstream.body, { status: upstream.status });
  } catch {
    return plgApiUnavailable();
  }
}
