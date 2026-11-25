import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, PATCH } from "@/app/api/threads/[id]/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const params = { params: Promise.resolve({ id: "t1" }) };
const request = (method: string, cookie?: string, body?: unknown) =>
  new NextRequest("http://localhost/api/threads/t1", {
    method,
    headers: { ...(cookie ? { cookie } : {}), ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });

describe("PATCH /api/threads/{id}", () => {
  it("renames the signed-in officer's conversation", async () => {
    const seen: { user: string | null; body: unknown }[] = [];
    server.use(
      http.patch(`${PLG_API}/threads/t1`, async ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), body: await request.json() });
        return HttpResponse.json({ thread_id: "t1", title: "Arrears", updated_at: "2026-11-02T10:00:00Z" });
      }),
    );

    const response = await PATCH(request("PATCH", "plg_user=S05", { title: "Arrears" }), params);

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ title: "Arrears" });
    expect(seen).toEqual([{ user: "S05", body: { title: "Arrears" } }]);
  });

  it("is 401 when not signed in", async () => {
    expect((await PATCH(request("PATCH", undefined, { title: "x" }), params)).status).toBe(401);
  });

  it("is 422 without a title", async () => {
    expect((await PATCH(request("PATCH", "plg_user=S05", { name: "x" }), params)).status).toBe(422);
  });

  it.each([404, 422])("passes on plg-api's %i", async (status) => {
    server.use(http.patch(`${PLG_API}/threads/t1`, () => HttpResponse.json({ detail: "no" }, { status })));

    expect((await PATCH(request("PATCH", "plg_user=S05", { title: "x" }), params)).status).toBe(status);
  });
});

describe("DELETE /api/threads/{id}", () => {
  it("deletes the signed-in officer's conversation", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.delete(`${PLG_API}/threads/t1`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const response = await DELETE(request("DELETE", "plg_user=S05"), params);

    expect(response.status).toBe(204);
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await DELETE(request("DELETE"), params)).status).toBe(401);
  });

  it.each([
    [404, "Thread not found"],
    [409, "This conversation is still answering: stop it or wait, then delete it"],
  ])("passes on plg-api's %i with its reason", async (status, detail) => {
    server.use(http.delete(`${PLG_API}/threads/t1`, () => HttpResponse.json({ detail }, { status })));

    const response = await DELETE(request("DELETE", "plg_user=S05"), params);

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail });
  });

  it("is 502 when plg-api can't be reached", async () => {
    server.use(http.delete(`${PLG_API}/threads/t1`, () => HttpResponse.error()));

    expect((await DELETE(request("DELETE", "plg_user=S05"), params)).status).toBe(502);
  });
});
