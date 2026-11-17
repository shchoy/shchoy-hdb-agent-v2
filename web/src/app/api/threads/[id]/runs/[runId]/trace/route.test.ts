import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/threads/[id]/runs/[runId]/trace/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const TRACE = "https://smith.langchain.com/o/tenant/projects/p/project/r/run-1?poll=true";
const params = { params: Promise.resolve({ id: "t1", runId: "run-1" }) };
const request = (cookie?: string) =>
  new NextRequest("http://localhost/api/threads/t1/runs/run-1/trace", { headers: cookie ? { cookie } : {} });

describe("GET /api/threads/{id}/runs/{runId}/trace", () => {
  it("redirects the signed-in developer to the run's trace in LangSmith", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/threads/t1/runs/run-1/trace`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json({ url: TRACE });
      }),
    );

    const response = await GET(request("plg_user=S08"), params);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(TRACE);
    expect(users).toEqual(["S08"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await GET(request(), params)).status).toBe(401);
  });

  it.each([
    [403, "Only developers can open traces"],
    [404, "No such answer in this conversation"],
    [503, "Tracing is off"],
  ])("passes on plg-api's %i", async (status, detail) => {
    server.use(http.get(`${PLG_API}/threads/t1/runs/run-1/trace`, () => HttpResponse.json({ detail }, { status })));

    const response = await GET(request("plg_user=S05"), params);

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail });
  });

  it("never redirects anywhere but an http(s) URL", async () => {
    server.use(
      http.get(`${PLG_API}/threads/t1/runs/run-1/trace`, () => HttpResponse.json({ url: "javascript:alert(1)" })),
    );

    expect((await GET(request("plg_user=S08"), params)).status).toBe(502);
  });
});
