// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/my-documents/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { myDocumentsFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const request = (cookie?: string) =>
  new NextRequest("http://localhost/api/my-documents", { headers: cookie ? { cookie } : {} });

describe("GET /api/my-documents", () => {
  it("relays the signed-in officer's uploads, the conversations that used them and their space", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/my-documents`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json(myDocumentsFixture("my_documents.json"));
      }),
    );

    const response = await GET(request("plg_user=S05"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(myDocumentsFixture("my_documents.json"));
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.get(`${PLG_API}/my-documents`, () => {
        called = true;
        return HttpResponse.json(myDocumentsFixture("my_documents.json"));
      }),
    );

    expect((await GET(request())).status).toBe(401);
    expect(called).toBe(false);
  });

  it("is 502 when plg-api can't be reached", async () => {
    server.use(http.get(`${PLG_API}/my-documents`, () => HttpResponse.error()));

    expect((await GET(request("plg_user=S05"))).status).toBe(502);
  });
});
