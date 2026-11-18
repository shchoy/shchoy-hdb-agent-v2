// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as listCategories } from "@/app/api/categories/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { categoriesFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

describe("/api/categories", () => {
  it("lists the document categories, asked as the signed-in officer", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/categories`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json(categoriesFixture());
      }),
    );

    const response = await listCategories(
      new NextRequest("http://localhost/api/categories", { headers: { cookie: "plg_user=S05" } }),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(categoriesFixture());
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.get(`${PLG_API}/categories`, () => {
        called = true;
        return HttpResponse.json({});
      }),
    );

    expect((await listCategories(new NextRequest("http://localhost/api/categories"))).status).toBe(401);
    expect(called).toBe(false);
  });

  it("relays a refusal from plg-api", async () => {
    server.use(http.get(`${PLG_API}/categories`, () => HttpResponse.json({ detail: "Unknown user" }, { status: 401 })));

    const response = await listCategories(
      new NextRequest("http://localhost/api/categories", { headers: { cookie: "plg_user=S99" } }),
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ detail: "Unknown user" });
  });

  it("is 502 when plg-api is unavailable", async () => {
    server.use(http.get(`${PLG_API}/categories`, () => HttpResponse.error()));

    expect(
      (
        await listCategories(
          new NextRequest("http://localhost/api/categories", { headers: { cookie: "plg_user=S05" } }),
        )
      ).status,
    ).toBe(502);
  });
});
