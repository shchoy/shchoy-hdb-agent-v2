import { NextResponse, type NextRequest } from "next/server";
import { getTraceLink, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * "View trace": sends a developer on to the LangSmith trace of one of their answers. plg-api decides who may
 * (developers, own threads) and its refusals are relayed; only an http(s) URL is ever redirected to.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; runId: string }> },
): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const { id, runId } = await params;
  let upstream: { status: number; body: unknown };
  try {
    upstream = await getTraceLink(staffId, id, runId);
  } catch {
    return plgApiUnavailable();
  }
  if (upstream.status !== 200) return NextResponse.json(upstream.body, { status: upstream.status });
  const url = (upstream.body as { url?: unknown } | null)?.url;
  if (typeof url !== "string" || !/^https?:\/\//.test(url)) {
    return NextResponse.json({ detail: "plg-api returned no usable trace URL" }, { status: 502 });
  }
  return NextResponse.redirect(url, 307);
}
