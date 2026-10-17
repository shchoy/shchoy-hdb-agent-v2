import { NextResponse, type NextRequest } from "next/server";
import { getDocument, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  try {
    const { status, body } = await getDocument(staffId, id);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
