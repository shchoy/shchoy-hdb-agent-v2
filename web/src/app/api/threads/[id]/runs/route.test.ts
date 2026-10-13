// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/threads/[id]/runs/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { fixture, sseResponse } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

function startRun(threadId: string, cookie?: string, body: unknown = { message: "Hi?" }) {
  return POST(
    new NextRequest(`http://localhost/api/threads/${threadId}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(cookie ? { cookie } : {}) },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id: threadId }) },
  );
}

describe("POST /api/threads/[id]/runs", () => {
  it("forwards the signed-in user and question to plg-api and streams the events through", async () => {
    const seen: { user: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${PLG_API}/threads/t1/runs`, async ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), body: await request.json() });
        return sseResponse(fixture("answer"));
      }),
    );

    const response = await startRun("t1", "plg_user=S04");

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toMatch(/^text\/event-stream/);
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toBe(fixture("answer"));
    expect(seen).toEqual([{ user: "S04", body: { message: "Hi?" } }]);
  });

  it("is 401 when not signed in, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.post(`${PLG_API}/threads/t1/runs`, () => {
        called = true;
        return sseResponse(fixture("answer"));
      }),
    );

    const response = await startRun("t1");

    expect(response.status).toBe(401);
    expect(called).toBe(false);
  });

  it("passes through plg-api's error status", async () => {
    server.use(
      http.post(`${PLG_API}/threads/nope/runs`, () =>
        HttpResponse.json({ detail: "Thread not found" }, { status: 404 }),
      ),
    );

    const response = await startRun("nope", "plg_user=S04");

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "Thread not found" });
  });

  it("is 400 without a question", async () => {
    const response = await startRun("t1", "plg_user=S04", {});

    expect(response.status).toBe(400);
  });

  it("is 502 when plg-api is unreachable", async () => {
    server.use(http.post(`${PLG_API}/threads/t1/runs`, () => HttpResponse.error()));

    const response = await startRun("t1", "plg_user=S04");

    expect(response.status).toBe(502);
  });
});
