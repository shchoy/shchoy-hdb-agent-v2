import { NextResponse, type NextRequest } from "next/server";
import { getMyDocuments, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Library → My documents (#106): the signed-in officer's uploads, the conversations that used them and their space. */
export async function GET(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  try {
    const { status, body } = await getMyDocuments(staffId);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
