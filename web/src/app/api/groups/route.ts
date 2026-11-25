import { NextResponse, type NextRequest } from "next/server";
import { createGroup, listGroups, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const notSignedIn = () => NextResponse.json({ detail: "Not signed in" }, { status: 401 });

/** The signed-in officer's conversation groups (#100). */
export async function GET(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  try {
    const { status, body } = await listGroups(staffId);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}

/** Create a group: `{name}` is passed on; plg-api's Group (201) or refusal (422) is relayed. */
export async function POST(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  const body: unknown = await request.json().catch(() => null);
  const name = body && typeof body === "object" && "name" in body ? body.name : undefined;
  if (typeof name !== "string") return NextResponse.json({ detail: "A name is needed" }, { status: 422 });
  try {
    const { status, body: created } = await createGroup(staffId, name);
    return NextResponse.json(created, { status });
  } catch {
    return plgApiUnavailable();
  }
}
