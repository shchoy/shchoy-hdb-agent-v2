import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { plgApiUnavailable, sendFeedback } from "@/lib/server/plg-api";
import { sessionStaffId } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const feedbackSchema = z.object({
  thread_id: z.string().min(1),
  run_id: z.string().min(1),
  score: z.enum(["up", "down"]),
  comment: z.string().default(""),
  correction: z.string().default(""),
  team_fact: z.string().default(""),
});

/** The officer's 👍/👎 (and correction) on one of their answers; plg-api's receipt or refusal is relayed. */
export async function POST(request: NextRequest): Promise<Response> {
  const staffId = sessionStaffId(request);
  if (!staffId) return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  const parsed = feedbackSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ detail: "Not feedback on an answer" }, { status: 400 });
  try {
    const { status, body } = await sendFeedback(staffId, parsed.data);
    return NextResponse.json(body, { status });
  } catch {
    return plgApiUnavailable();
  }
}
