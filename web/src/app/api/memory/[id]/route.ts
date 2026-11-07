import { NextResponse, type NextRequest } from "next/server";
import { editMemory, forgetMemory, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId)
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  try {
    const { status, body } = await editMemory(staffId, id, await request.json());
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}

export async function DELETE(request: NextRequest, { params }: Params): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId)
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  try {
    const { status, body } = await forgetMemory(staffId, id);
    return status === 204 ? new Response(null, { status }) : NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
