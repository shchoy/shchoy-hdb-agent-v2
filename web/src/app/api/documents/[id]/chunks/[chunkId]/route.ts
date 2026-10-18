import { NextResponse, type NextRequest } from "next/server";
import { getChunkLocation, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function offset(value: string | null): number | undefined {
  const n = value === null ? NaN : Number(value);
  return Number.isInteger(n) && n >= 0 ? n : undefined;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; chunkId: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id, chunkId } = await params;
  const query = request.nextUrl.searchParams;
  try {
    const { status, body } = await getChunkLocation(staffId, id, chunkId, {
      start: offset(query.get("start")),
      end: offset(query.get("end")),
    });
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
