import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, PATCH } from "@/app/api/groups/[id]/route";
import { PUT as REORDER } from "@/app/api/groups/order/route";
import { GET, POST } from "@/app/api/groups/route";
import { PUT } from "@/app/api/threads/[id]/group/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const request = (url: string, method: string, cookie?: string, body?: unknown) =>
  new NextRequest(`http://localhost${url}`, {
    method,
    headers: { ...(cookie ? { cookie } : {}), ...(body !== undefined ? { "content-type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

const group = { params: Promise.resolve({ id: "g1" }) };
const thread = { params: Promise.resolve({ id: "t1" }) };
const signedIn = "plg_user=S05";

/** Records what plg-api received: the officer header and the JSON body. */
function recording(method: "get" | "post" | "patch" | "delete" | "put", path: string, reply: () => Response) {
  const seen: { user: string | null; body: unknown }[] = [];
  server.use(
    http[method](`${PLG_API}${path}`, async ({ request }) => {
      seen.push({ user: request.headers.get("x-plg-user"), body: await request.json().catch(() => null) });
      return reply();
    }),
  );
  return seen;
}

describe("/api/groups", () => {
  it("lists the signed-in officer's groups", async () => {
    const seen = recording("get", "/groups", () => HttpResponse.json([{ group_id: "g1", name: "Arrears" }]));

    const response = await GET(request("/api/groups", "GET", signedIn));

    expect(await response.json()).toEqual([{ group_id: "g1", name: "Arrears" }]);
    expect(seen.map((s) => s.user)).toEqual(["S05"]);
  });

  it("creates a group", async () => {
    const seen = recording("post", "/groups", () => HttpResponse.json({ group_id: "g1", name: "Arrears" }, { status: 201 }));

    const response = await POST(request("/api/groups", "POST", signedIn, { name: "Arrears" }));

    expect(response.status).toBe(201);
    expect(seen).toEqual([{ user: "S05", body: { name: "Arrears" } }]);
  });

  it("is 401 when not signed in and 422 without a name", async () => {
    expect((await GET(request("/api/groups", "GET"))).status).toBe(401);
    expect((await POST(request("/api/groups", "POST", undefined, { name: "x" }))).status).toBe(401);
    expect((await POST(request("/api/groups", "POST", signedIn, { title: "x" }))).status).toBe(422);
  });
});

describe("/api/groups/{id}", () => {
  it("renames a group", async () => {
    const seen = recording("patch", "/groups/g1", () => HttpResponse.json({ group_id: "g1", name: "Renewals" }));

    const response = await PATCH(request("/api/groups/g1", "PATCH", signedIn, { name: "Renewals" }), group);

    expect(await response.json()).toEqual({ group_id: "g1", name: "Renewals" });
    expect(seen).toEqual([{ user: "S05", body: { name: "Renewals" } }]);
  });

  it("deletes a group", async () => {
    const seen = recording("delete", "/groups/g1", () => new HttpResponse(null, { status: 204 }));

    const response = await DELETE(request("/api/groups/g1", "DELETE", signedIn), group);

    expect(response.status).toBe(204);
    expect(seen.map((s) => s.user)).toEqual(["S05"]);
  });

  it.each([404, 422])("passes on plg-api's %i", async (status) => {
    server.use(
      http.patch(`${PLG_API}/groups/g1`, () => HttpResponse.json({ detail: "no" }, { status })),
      http.delete(`${PLG_API}/groups/g1`, () => HttpResponse.json({ detail: "no" }, { status })),
    );

    expect((await PATCH(request("/api/groups/g1", "PATCH", signedIn, { name: "x" }), group)).status).toBe(status);
    expect((await DELETE(request("/api/groups/g1", "DELETE", signedIn), group)).status).toBe(status);
  });

  it("is 401 when not signed in", async () => {
    expect((await PATCH(request("/api/groups/g1", "PATCH", undefined, { name: "x" }), group)).status).toBe(401);
    expect((await DELETE(request("/api/groups/g1", "DELETE"), group)).status).toBe(401);
  });
});

describe("PUT /api/groups/order", () => {
  it("passes the new order on and relays the reordered groups", async () => {
    const reordered = [{ group_id: "g2", name: "Renewals" }, { group_id: "g1", name: "Arrears" }];
    const seen = recording("put", "/groups/order", () => HttpResponse.json(reordered));

    const response = await REORDER(request("/api/groups/order", "PUT", signedIn, { group_ids: ["g2", "g1"] }));

    expect(await response.json()).toEqual(reordered);
    expect(seen).toEqual([{ user: "S05", body: { group_ids: ["g2", "g1"] } }]);
  });

  it("is 401 when not signed in, 422 without a list of IDs, and passes on plg-api's 409", async () => {
    server.use(http.put(`${PLG_API}/groups/order`, () => HttpResponse.json({ detail: "changed" }, { status: 409 })));

    expect((await REORDER(request("/api/groups/order", "PUT", undefined, { group_ids: [] }))).status).toBe(401);
    expect((await REORDER(request("/api/groups/order", "PUT", signedIn, { group_ids: "g1" }))).status).toBe(422);
    expect((await REORDER(request("/api/groups/order", "PUT", signedIn, { group_ids: [1] }))).status).toBe(422);
    expect((await REORDER(request("/api/groups/order", "PUT", signedIn, { group_ids: ["g1"] }))).status).toBe(409);
  });
});

describe("PUT /api/threads/{id}/group", () => {
  it("moves a conversation into a group and back to Recent", async () => {
    const seen = recording("put", "/threads/t1/group", () =>
      HttpResponse.json({ thread_id: "t1", title: "Arrears", updated_at: "2026-11-02T10:00:00Z", group_id: "g1" }),
    );

    const moved = await PUT(request("/api/threads/t1/group", "PUT", signedIn, { group_id: "g1" }), thread);
    await PUT(request("/api/threads/t1/group", "PUT", signedIn, { group_id: null }), thread);

    expect(await moved.json()).toMatchObject({ group_id: "g1" });
    expect(seen).toEqual([
      { user: "S05", body: { group_id: "g1" } },
      { user: "S05", body: { group_id: null } },
    ]);
  });

  it("is 401 when not signed in, 422 without a group_id, and passes on plg-api's 404", async () => {
    server.use(http.put(`${PLG_API}/threads/t1/group`, () => HttpResponse.json({ detail: "Group not found" }, { status: 404 })));

    expect((await PUT(request("/api/threads/t1/group", "PUT", undefined, { group_id: "g1" }), thread)).status).toBe(401);
    expect((await PUT(request("/api/threads/t1/group", "PUT", signedIn, {}), thread)).status).toBe(422);
    expect((await PUT(request("/api/threads/t1/group", "PUT", signedIn, { group_id: "g9" }), thread)).status).toBe(404);
  });
});
