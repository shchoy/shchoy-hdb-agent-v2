// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as listApprovals } from "@/app/api/approvals/route";
import { GET as auditTrail } from "@/app/api/audit/route";
import { POST as resume } from "@/app/api/threads/[id]/resume/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { approvalsFixture, sseResponse } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const SIGNED_IN = { cookie: "plg_user=S05" };

function decide(threadId: string, body: unknown, headers: Record<string, string> = SIGNED_IN) {
  return resume(
    new NextRequest(`http://localhost/api/threads/${threadId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id: threadId }) },
  );
}

const REJECT = { action_id: "a1", version: 1, decision: "reject", reason: "The tenant paid yesterday." };

describe("/api/approvals", () => {
  it("lists the signed-in officer's pending approvals", async () => {
    const seen: { user: string | null; status: string | null }[] = [];
    server.use(
      http.get(`${PLG_API}/approvals`, ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), status: new URL(request.url).searchParams.get("status") });
        return HttpResponse.json(approvalsFixture("pending.json"));
      }),
    );

    const response = await listApprovals(new NextRequest("http://localhost/api/approvals", { headers: SIGNED_IN }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(approvalsFixture("pending.json"));
    expect(seen).toEqual([{ user: "S05", status: "pending" }]);
  });

  it("is 401 when not signed in", async () => {
    expect((await listApprovals(new NextRequest("http://localhost/api/approvals"))).status).toBe(401);
  });
});

describe("/api/audit", () => {
  it("relays the signed-in officer's audit trail", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/audit`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json(approvalsFixture("audit.json"));
      }),
    );

    const response = await auditTrail(new NextRequest("http://localhost/api/audit", { headers: SIGNED_IN }));

    expect(await response.json()).toEqual(approvalsFixture("audit.json"));
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await auditTrail(new NextRequest("http://localhost/api/audit"))).status).toBe(401);
  });
});

describe("POST /api/threads/[id]/resume", () => {
  it("forwards the decision as the signed-in officer and streams the result through", async () => {
    const seen: { user: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${PLG_API}/threads/t1/resume`, async ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), body: await request.json() });
        return sseResponse(approvalsFixture("reject.sse"));
      }),
    );

    const response = await decide("t1", REJECT);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toMatch(/^text\/event-stream/);
    expect(await response.text()).toBe(approvalsFixture("reject.sse"));
    expect(seen).toEqual([{ user: "S05", body: { ...REJECT, edits: {} } }]);
  });

  it("relays plg-api's refusal and its reason", async () => {
    server.use(
      http.post(`${PLG_API}/threads/t1/resume`, () =>
        HttpResponse.json({ detail: "Your role can't approve this action" }, { status: 403 }),
      ),
    );

    const response = await decide("t1", { ...REJECT, decision: "approve", reason: "" });

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "Your role can't approve this action" });
  });

  it("is 401 when not signed in, and 400 for a body that isn't a decision, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.post(`${PLG_API}/threads/t1/resume`, () => {
        called = true;
        return sseResponse(approvalsFixture("reject.sse"));
      }),
    );

    expect((await decide("t1", REJECT, {})).status).toBe(401);
    expect((await decide("t1", { decision: "send it" })).status).toBe(400);
    expect(called).toBe(false);
  });
});
