// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, PATCH } from "@/app/api/uploads/[id]/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { uploadFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const ID = "upload-0123456789abcdef";
const params = { params: Promise.resolve({ id: ID }) };
const request = (method: string, cookie?: string, body?: unknown) =>
  new NextRequest(`http://localhost/api/uploads/${ID}`, {
    method,
    headers: { ...(cookie ? { cookie } : {}), ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });

describe("PATCH /api/uploads/{id}", () => {
  it("renames the signed-in officer's upload", async () => {
    const seen: { user: string | null; body: unknown }[] = [];
    server.use(
      http.patch(`${PLG_API}/uploads/${ID}`, async ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), body: await request.json() });
        return HttpResponse.json({ ...uploadFixture(), upload_id: ID, title: "Kiosk visit" });
      }),
    );

    const response = await PATCH(request("PATCH", "plg_user=S05", { title: "Kiosk visit" }), params);

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ upload_id: ID, title: "Kiosk visit" });
    expect(seen).toEqual([{ user: "S05", body: { title: "Kiosk visit" } }]);
  });

  it("is 401 when not signed in and 422 without a title, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.patch(`${PLG_API}/uploads/${ID}`, () => {
        called = true;
        return HttpResponse.json(uploadFixture());
      }),
    );

    expect((await PATCH(request("PATCH", undefined, { title: "x" }), params)).status).toBe(401);
    expect((await PATCH(request("PATCH", "plg_user=S05", { name: "x" }), params)).status).toBe(422);
    expect(called).toBe(false);
  });

  it.each([
    [404, "Upload not found"],
    [422, "String should have at most 120 characters"],
  ])("passes on plg-api's %i with its detail", async (status, detail) => {
    server.use(http.patch(`${PLG_API}/uploads/${ID}`, () => HttpResponse.json({ detail }, { status })));

    const response = await PATCH(request("PATCH", "plg_user=S05", { title: "x" }), params);

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail });
  });

  it("is 502 when plg-api can't be reached", async () => {
    server.use(http.patch(`${PLG_API}/uploads/${ID}`, () => HttpResponse.error()));

    expect((await PATCH(request("PATCH", "plg_user=S05", { title: "x" }), params)).status).toBe(502);
  });
});

describe("DELETE /api/uploads/{id}", () => {
  it("deletes the signed-in officer's upload", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.delete(`${PLG_API}/uploads/${ID}`, ({ request }) => {
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

  it("passes on plg-api's 404 for an upload not theirs", async () => {
    server.use(
      http.delete(`${PLG_API}/uploads/${ID}`, () => HttpResponse.json({ detail: "Upload not found" }, { status: 404 })),
    );

    const response = await DELETE(request("DELETE", "plg_user=S05"), params);

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "Upload not found" });
  });

  it("is 502 when plg-api can't be reached", async () => {
    server.use(http.delete(`${PLG_API}/uploads/${ID}`, () => HttpResponse.error()));

    expect((await DELETE(request("DELETE", "plg_user=S05"), params)).status).toBe(502);
  });
});
