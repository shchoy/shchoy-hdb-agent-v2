// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as latestReport } from "@/app/api/audit/reports/latest/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { auditReportFixture } from "@/test/sse";

const URL = "http://localhost/api/audit/reports/latest";
const NONE = "No corpus audit has run yet: run `plg audit`.";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

function signedIn(staffId = "S05") {
  return new NextRequest(URL, { headers: { cookie: `plg_user=${staffId}` } });
}

describe("/api/audit/reports/latest", () => {
  it("relays the latest audit report, asked as the signed-in officer", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/audit/reports/latest`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json(auditReportFixture());
      }),
    );

    const response = await latestReport(signedIn());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(auditReportFixture());
    expect(users).toEqual(["S05"]);
  });

  it("relays plg-api's 404 when no audit has run yet", async () => {
    server.use(http.get(`${PLG_API}/audit/reports/latest`, () => HttpResponse.json({ detail: NONE }, { status: 404 })));

    const response = await latestReport(signedIn());

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: NONE });
  });

  it("relays a refusal from plg-api", async () => {
    server.use(
      http.get(`${PLG_API}/audit/reports/latest`, () => HttpResponse.json({ detail: "Unknown user" }, { status: 401 })),
    );

    const response = await latestReport(signedIn("S99"));

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ detail: "Unknown user" });
  });

  it("is 401 when not signed in, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.get(`${PLG_API}/audit/reports/latest`, () => {
        called = true;
        return HttpResponse.json({});
      }),
    );

    expect((await latestReport(new NextRequest(URL))).status).toBe(401);
    expect(called).toBe(false);
  });

  it("is 502 when plg-api is unavailable", async () => {
    server.use(http.get(`${PLG_API}/audit/reports/latest`, () => HttpResponse.error()));

    expect((await latestReport(signedIn())).status).toBe(502);
  });
});
