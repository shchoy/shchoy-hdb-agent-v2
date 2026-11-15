import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { decideCuration, plgApiUnavailable } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const decisionSchema = z.object({
  action_id: z.string().min(1),
  version: z.number().int(),
  decision: z.enum(["approve", "edit", "reject"]),
  edits: z.record(z.string(), z.string()).default({}),
  reason: z.string().default(""),
});

/** A curator's decision on a pending proposal. plg-api checks it (curator, version, reason, edits, SQL); a refusal is
 * relayed with its reason. */
export async function POST(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const parsed = decisionSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ detail: "Not a decision on a proposal" }, { status: 400 });
  try {
    const { status, body } = await decideCuration(staffId, parsed.data);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
