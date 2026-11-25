import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PUT as PIN_GROUP } from "@/app/api/groups/[id]/pin/route";
import { PUT as PIN_THREAD } from "@/app/api/threads/[id]/pin/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const request = (url: string, cookie?: string, body?: unknown) =>
  new NextRequest(`http://localhost${url}`, {
    method: "PUT",
    headers: { ...(cookie ? { cookie } : {}), "content-type": "application/json" },
    body: JSON.stringify(body),
  });

const params = (id: string) => ({ params: Promise.resolve({ id }) });
const signedIn = "plg_user=S05";

function recording(path: string, reply: () => Response) {
  const seen: { user: string | null; body: unknown }[] = [];
  server.use(
    http.put(`${PLG_API}${path}`, async ({ request }) => {
      seen.push({ user: request.headers.get("x-plg-user"), body: await request.json().catch(() => null) });
      return reply();
    }),
  );
  return seen;
}

describe("pins (#102)", () => {
  it("pins a conversation for the signed-in officer", async () => {
    const summary = { thread_id: "t1", title: "Arrears", updated_at: "2026-11-25T00:00:00Z", group_id: null, pinned: 0 };
    const seen = recording("/threads/t1/pin", () => HttpResponse.json(summary));

    const response = await PIN_THREAD(request("/api/threads/t1/pin", signedIn, { pinned: true }), params("t1"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(summary);
    expect(seen).toEqual([{ user: "S05", body: { pinned: true } }]);
  });

  it("unpins a group and relays plg-api's refusal", async () => {
    const seen = recording("/groups/g1/pin", () => HttpResponse.json({ detail: "Group not found" }, { status: 404 }));

    const response = await PIN_GROUP(request("/api/groups/g1/pin", signedIn, { pinned: false }), params("g1"));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "Group not found" });
    expect(seen).toEqual([{ user: "S05", body: { pinned: false } }]);
  });

  it("is 401 when not signed in and 422 without a pinned flag", async () => {
    expect((await PIN_THREAD(request("/api/threads/t1/pin", undefined, { pinned: true }), params("t1"))).status).toBe(401);
    expect((await PIN_GROUP(request("/api/groups/g1/pin", undefined, { pinned: true }), params("g1"))).status).toBe(401);
    expect((await PIN_THREAD(request("/api/threads/t1/pin", signedIn, { pinned: "yes" }), params("t1"))).status).toBe(422);
    expect((await PIN_GROUP(request("/api/groups/g1/pin", signedIn, {}), params("g1"))).status).toBe(422);
  });
});
