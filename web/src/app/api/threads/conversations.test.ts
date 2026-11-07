// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as list } from "@/app/api/threads/route";
import { GET as detail } from "@/app/api/threads/[id]/route";
import { GET as latest } from "@/app/api/threads/[id]/runs/latest/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const params = { params: Promise.resolve({ id: "t1" }) };
const get = (path: string, headers: Record<string, string> = {}) =>
  new NextRequest(`http://localhost${path}`, { headers });

describe("conversation routes", () => {
  it("list the signed-in user's threads as that user", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/threads`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json([
          { thread_id: "t1", title: "hi", updated_at: "x" },
        ]);
      }),
    );

    const response = await list(
      get("/api/threads", { cookie: "plg_user=S04" }),
    );

    expect(await response.json()).toHaveLength(1);
    expect(users).toEqual(["S04"]);
  });

  it("are 401 when not signed in", async () => {
    expect((await list(get("/api/threads"))).status).toBe(401);
    expect((await detail(get("/api/threads/t1"), params)).status).toBe(401);
    expect(
      (await latest(get("/api/threads/t1/runs/latest"), params)).status,
    ).toBe(401);
  });

  it("pass on plg-api's 404 for someone else's thread", async () => {
    server.use(
      http.get(`${PLG_API}/threads/t1`, () =>
        HttpResponse.json({ detail: "Thread not found" }, { status: 404 }),
      ),
    );

    const response = await detail(
      get("/api/threads/t1", { cookie: "plg_user=S04" }),
      params,
    );

    expect(response.status).toBe(404);
  });

  it("resume a run, forwarding Last-Event-ID", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/threads/t1/runs/latest`, ({ request }) => {
        seen.push(request.headers.get("last-event-id"));
        return new HttpResponse("id: 4\nevent: done\ndata: {}\n\n", {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );

    const response = await latest(
      get("/api/threads/t1/runs/latest", {
        cookie: "plg_user=S04",
        "last-event-id": "3",
      }),
      params,
    );

    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(seen).toEqual(["3"]);
  });
});
