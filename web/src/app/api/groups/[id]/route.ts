import { NextResponse, type NextRequest } from "next/server";
import { deleteGroup, plgApiUnavailable, renameGroup } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

const notSignedIn = () => NextResponse.json({ detail: "Not signed in" }, { status: 401 });

/** Rename a group: `{name}` is passed on; plg-api's Group or refusal (404, 422) is relayed. */
export async function PATCH(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  const { id } = await params;
  const body: unknown = await request.json().catch(() => null);
  const name = body && typeof body === "object" && "name" in body ? body.name : undefined;
  if (typeof name !== "string") return NextResponse.json({ detail: "A name is needed" }, { status: 422 });
  try {
    const upstream = await renameGroup(staffId, id, name);
    return NextResponse.json(upstream.body, { status: upstream.status });
  } catch {
    return plgApiUnavailable();
  }
}

/** Delete a group (its conversations go back to Recent): 204, or plg-api's refusal (404) relayed. */
export async function DELETE(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  const { id } = await params;
  let upstream: { status: number; body: unknown };
  try {
    upstream = await deleteGroup(staffId, id);
  } catch {
    return plgApiUnavailable();
  }
  if (upstream.status === 204) return new Response(null, { status: 204 });
  return NextResponse.json(upstream.body, { status: upstream.status });
}
