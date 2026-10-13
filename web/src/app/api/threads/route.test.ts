// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/threads/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

function createThread(cookie?: string): Promise<Response> {
  return POST(
    new NextRequest("http://localhost/api/threads", {
      method: "POST",
      headers: cookie ? { cookie } : {},
    }),
  );
}

describe("POST /api/threads", () => {
  it("creates the thread on plg-api as the signed-in user", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.post(`${PLG_API}/threads`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json({ thread_id: "t1" }, { status: 201 });
      }),
    );

    const response = await createThread("plg_user=S04");

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ thread_id: "t1" });
    expect(users).toEqual(["S04"]);
  });

  it("is 401 when not signed in", async () => {
    const response = await createThread();

    expect(response.status).toBe(401);
  });

  it("passes on plg-api's refusal of the user", async () => {
    server.use(
      http.post(`${PLG_API}/threads`, () =>
        HttpResponse.json({ detail: "Unknown or missing X-PLG-User" }, { status: 401 }),
      ),
    );

    const response = await createThread("plg_user=S99");

    expect(response.status).toBe(401);
  });
});
