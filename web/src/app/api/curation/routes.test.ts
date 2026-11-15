// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as listCuration } from "@/app/api/curation/route";
import { POST as decide } from "@/app/api/curation/decide/route";
import { POST as giveFeedback } from "@/app/api/feedback/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { feedbackFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const SIGNED_IN = { cookie: "plg_user=S05" };
const CURATOR = { cookie: "plg_user=S03" };

function post(path: string, body: unknown, headers: Record<string, string> = SIGNED_IN) {
  return new NextRequest(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

const thread = feedbackFixture("thread.json") as { thread_id: string; turns: { run_id: string }[] };
const UP = { thread_id: thread.thread_id, run_id: thread.turns[0].run_id, score: "up" };

describe("POST /api/feedback", () => {
  it("sends the feedback as the signed-in officer and relays the receipt", async () => {
    const seen: { user: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${PLG_API}/feedback`, async ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), body: await request.json() });
        return HttpResponse.json(feedbackFixture("receipt_up.json"), { status: 201 });
      }),
    );

    const response = await giveFeedback(post("/api/feedback", UP));

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(feedbackFixture("receipt_up.json"));
    expect(seen).toEqual([{ user: "S05", body: { ...UP, comment: "", correction: "", team_fact: "" } }]);
  });

  it("relays plg-api's refusal", async () => {
    server.use(
      http.post(`${PLG_API}/feedback`, () =>
        HttpResponse.json({ detail: "No such answer in this conversation" }, { status: 404 }),
      ),
    );

    const response = await giveFeedback(post("/api/feedback", UP));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "No such answer in this conversation" });
  });

  it("is 401 when not signed in, and 400 for a body that isn't feedback, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.post(`${PLG_API}/feedback`, () => {
        called = true;
        return HttpResponse.json(feedbackFixture("receipt_up.json"), { status: 201 });
      }),
    );

    expect((await giveFeedback(post("/api/feedback", UP, {}))).status).toBe(401);
    expect((await giveFeedback(post("/api/feedback", { ...UP, score: "meh" }))).status).toBe(400);
    expect(called).toBe(false);
  });
});

describe("GET /api/curation", () => {
  it("lists the pending proposals the signed-in curator may decide", async () => {
    const seen: { user: string | null; status: string | null }[] = [];
    server.use(
      http.get(`${PLG_API}/curation`, ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), status: new URL(request.url).searchParams.get("status") });
        return HttpResponse.json(feedbackFixture("curation.json"));
      }),
    );

    const response = await listCuration(new NextRequest("http://localhost/api/curation", { headers: CURATOR }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(feedbackFixture("curation.json"));
    expect(seen).toEqual([{ user: "S03", status: "pending" }]);
  });

  it("is 401 when not signed in", async () => {
    expect((await listCuration(new NextRequest("http://localhost/api/curation"))).status).toBe(401);
  });
});

describe("POST /api/curation/decide", () => {
  const fact = feedbackFixture("curation.json").find((a) => a.action_type === "approve_team_fact") as {
    action_id: string;
    version: number;
  };
  const APPROVE = { action_id: fact.action_id, version: fact.version, decision: "approve" };

  it("forwards the curator's decision and relays the decided proposal", async () => {
    const seen: { user: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${PLG_API}/curation/decide`, async ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), body: await request.json() });
        return HttpResponse.json(feedbackFixture("decided.json"));
      }),
    );

    const response = await decide(post("/api/curation/decide", APPROVE, CURATOR));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(feedbackFixture("decided.json"));
    expect(seen).toEqual([{ user: "S03", body: { ...APPROVE, edits: {}, reason: "" } }]);
  });

  it("relays plg-api's refusal and its reason", async () => {
    server.use(
      http.post(`${PLG_API}/curation/decide`, () =>
        HttpResponse.json({ detail: "Only a curator other than the proposer can approve it" }, { status: 403 }),
      ),
    );

    const response = await decide(post("/api/curation/decide", APPROVE));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "Only a curator other than the proposer can approve it" });
  });

  it("is 401 when not signed in, and 400 for a body that isn't a decision, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.post(`${PLG_API}/curation/decide`, () => {
        called = true;
        return HttpResponse.json(feedbackFixture("decided.json"));
      }),
    );

    expect((await decide(post("/api/curation/decide", APPROVE, {}))).status).toBe(401);
    expect((await decide(post("/api/curation/decide", { decision: "maybe" }))).status).toBe(400);
    expect(called).toBe(false);
  });
});
