import { NextResponse, type NextRequest } from "next/server";
import { getDraftFile, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Headers plg-api sets on the download: the DOCX type and an attachment filename. */
const RELAYED_HEADERS = ["content-type", "content-disposition", "x-content-type-options"];

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id } = await params;
  let upstream: Response;
  try {
    upstream = await getDraftFile(staffId, id);
  } catch {
    return plgApiUnavailable();
  }
  const headers = new Headers();
  for (const name of RELAYED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
