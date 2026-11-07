import { NextResponse, type NextRequest } from "next/server";
import { listMemory, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId)
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  try {
    const { status, body } = await listMemory(staffId);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
