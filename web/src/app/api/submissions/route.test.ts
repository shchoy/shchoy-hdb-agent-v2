// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as listSubmissions } from "@/app/api/submissions/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { submissionsFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

describe("/api/submissions", () => {
  it("lists the applications with a submission bundle, asked as the signed-in officer", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/submissions`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json(submissionsFixture());
      }),
    );

    const response = await listSubmissions(
      new NextRequest("http://localhost/api/submissions", { headers: { cookie: "plg_user=S05" } }),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(submissionsFixture());
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.get(`${PLG_API}/submissions`, () => {
        called = true;
        return HttpResponse.json([]);
      }),
    );

    expect((await listSubmissions(new NextRequest("http://localhost/api/submissions"))).status).toBe(401);
    expect(called).toBe(false);
  });

  it("is 502 when plg-api is unavailable", async () => {
    server.use(http.get(`${PLG_API}/submissions`, () => HttpResponse.error()));

    expect(
      (
        await listSubmissions(
          new NextRequest("http://localhost/api/submissions", { headers: { cookie: "plg_user=S05" } }),
        )
      ).status,
    ).toBe(502);
  });
});
