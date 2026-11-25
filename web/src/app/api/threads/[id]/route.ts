import { NextResponse, type NextRequest } from "next/server";
import { deleteThread, getThread, plgApiUnavailable, renameThread } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

const notSignedIn = () => NextResponse.json({ detail: "Not signed in" }, { status: 401 });

export async function GET(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  const { id } = await params;
  try {
    const { status, body } = await getThread(staffId, id);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}

/** Rename: `{title}` is passed on; plg-api's ThreadSummary or refusal (404, 422) is relayed. */
export async function PATCH(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  const { id } = await params;
  const body: unknown = await request.json().catch(() => null);
  const title = body && typeof body === "object" && "title" in body ? body.title : undefined;
  if (typeof title !== "string") return NextResponse.json({ detail: "A title is needed" }, { status: 422 });
  try {
    const upstream = await renameThread(staffId, id, title);
    return NextResponse.json(upstream.body, { status: upstream.status });
  } catch {
    return plgApiUnavailable();
  }
}

/** Delete: 204, or plg-api's refusal (404, 409 still answering / an action awaiting approval) relayed. */
export async function DELETE(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return notSignedIn();
  const { id } = await params;
  let upstream: { status: number; body: unknown };
  try {
    upstream = await deleteThread(staffId, id);
  } catch {
    return plgApiUnavailable();
  }
  if (upstream.status === 204) return new Response(null, { status: 204 });
  return NextResponse.json(upstream.body, { status: upstream.status });
}
