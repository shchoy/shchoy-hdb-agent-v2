import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { listPersonas, plgApiUnavailable } from "@/lib/server/plg-api";
import { clearSession, setSession } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const signInSchema = z.object({ staff_id: z.string().min(1) });

/** Mock sign-in: accepts any persona plg-api knows about. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const parsed = signInSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ detail: "staff_id is required" }, { status: 400 });
  }
  let personas;
  try {
    personas = await listPersonas();
  } catch {
    return plgApiUnavailable();
  }
  if (!personas.some((p) => p.staff_id === parsed.data.staff_id)) {
    return NextResponse.json({ detail: "Unknown staff ID" }, { status: 401 });
  }
  const response = new NextResponse(null, { status: 204 });
  setSession(response, parsed.data.staff_id);
  return response;
}

export async function DELETE(): Promise<NextResponse> {
  const response = new NextResponse(null, { status: 204 });
  clearSession(response);
  return response;
}
