import { NextResponse, type NextRequest } from "next/server";
import { listUploads, plgApiUnavailable, uploadFile } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Uploads a file into the officer's private library (#103). The request body is the file's bytes, streamed through to
 * plg-api unbuffered; its reply (the Upload, or a refusal with its status and detail) is relayed.
 */
export async function POST(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const filename = request.nextUrl.searchParams.get("filename")?.trim();
  if (!filename) return NextResponse.json({ detail: "filename is required" }, { status: 400 });
  let upstream: Response;
  try {
    upstream = await uploadFile(staffId, filename, request.body, {
      contentType: request.headers.get("content-type"),
      contentLength: request.headers.get("content-length"),
      signal: request.signal,
    });
  } catch {
    return plgApiUnavailable();
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

/** The officer's own uploads, newest first. */
export async function GET(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  try {
    const { status, body } = await listUploads(staffId);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
