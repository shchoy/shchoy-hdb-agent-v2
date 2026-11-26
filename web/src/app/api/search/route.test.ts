// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as search } from "@/app/api/search/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const RESULTS = {
  conversations: [
    {
      thread_id: "t1",
      title: "Lucky Star arrears",
      updated_at: "2026-11-20T01:00:00+00:00",
      group_id: null,
      group_name: null,
      pinned: null,
      matched: "answer",
      message_index: 2,
      snippet: [{ text: "The " }, { text: "arrears", match: true }, { text: " are S$4,000." }],
    },
  ],
};

describe("/api/search", () => {
  it("relays the signed-in officer's search, query and all", async () => {
    const seen: { user: string | null; q: string | null }[] = [];
    server.use(
      http.get(`${PLG_API}/search`, ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), q: new URL(request.url).searchParams.get("q") });
        return HttpResponse.json(RESULTS);
      }),
    );

    const response = await search(
      new NextRequest("http://localhost/api/search?q=arrears%20%26%20rent", { headers: { cookie: "plg_user=S05" } }),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(RESULTS);
    expect(seen).toEqual([{ user: "S05", q: "arrears & rent" }]);
  });

  it("is 401 when not signed in", async () => {
    expect((await search(new NextRequest("http://localhost/api/search?q=x"))).status).toBe(401);
  });
});
