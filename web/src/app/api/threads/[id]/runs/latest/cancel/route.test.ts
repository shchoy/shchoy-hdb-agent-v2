import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/threads/[id]/runs/latest/cancel/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const params = { params: Promise.resolve({ id: "t1" }) };
const request = (cookie?: string) =>
  new NextRequest("http://localhost/api/threads/t1/runs/latest/cancel", {
    method: "POST",
    headers: cookie ? { cookie } : {},
  });

describe("POST /api/threads/{id}/runs/latest/cancel", () => {
  it("asks plg-api to stop the signed-in officer's running answer", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.post(`${PLG_API}/threads/t1/runs/latest/cancel`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const response = await POST(request("plg_user=S05"), params);

    expect(response.status).toBe(204);
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await POST(request(), params)).status).toBe(401);
  });

  it.each([
    [404, "Thread not found"],
    [409, "Nothing is running on this thread"],
  ])("passes on plg-api's %i", async (status, detail) => {
    server.use(
      http.post(`${PLG_API}/threads/t1/runs/latest/cancel`, () => HttpResponse.json({ detail }, { status })),
    );

    const response = await POST(request("plg_user=S05"), params);

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail });
  });

  it("is 502 when plg-api can't be reached", async () => {
    server.use(http.post(`${PLG_API}/threads/t1/runs/latest/cancel`, () => HttpResponse.error()));

    expect((await POST(request("plg_user=S05"), params)).status).toBe(502);
  });
});
