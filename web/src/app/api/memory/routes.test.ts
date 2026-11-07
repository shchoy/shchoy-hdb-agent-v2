// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/memory/route";
import { DELETE } from "@/app/api/memory/[id]/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

describe("/api/memory", () => {
  it("lists memories as the signed-in user", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/memory`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json([]);
      }),
    );

    const response = await GET(new NextRequest("http://localhost/api/memory", { headers: { cookie: "plg_user=S04" } }));

    expect(response.status).toBe(200);
    expect(users).toEqual(["S04"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await GET(new NextRequest("http://localhost/api/memory"))).status).toBe(401);
  });

  it("relays a forget, and a 404 for someone else's memory", async () => {
    server.use(
      http.delete(`${PLG_API}/memory/mine`, () => new HttpResponse(null, { status: 204 })),
      http.delete(`${PLG_API}/memory/theirs`, () => HttpResponse.json({ detail: "Memory not found" }, { status: 404 })),
    );
    const call = (id: string) =>
      DELETE(new NextRequest(`http://localhost/api/memory/${id}`, { method: "DELETE", headers: { cookie: "plg_user=S04" } }), {
        params: Promise.resolve({ id }),
      });

    expect((await call("mine")).status).toBe(204);
    expect((await call("theirs")).status).toBe(404);
  });
});
