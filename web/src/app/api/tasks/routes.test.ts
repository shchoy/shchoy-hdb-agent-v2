// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as getDigest } from "@/app/api/tasks/digest/route";
import { GET as getTeam } from "@/app/api/tasks/team/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { tasksFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const SIGNED_IN = { headers: { cookie: "plg_user=S04" } };

describe("/api/tasks/digest", () => {
  it("forwards the officer and how many tasks to show, asked as the signed-in officer", async () => {
    const seen: { user: string | null; query: string }[] = [];
    server.use(
      http.get(`${PLG_API}/tasks/digest`, ({ request }) => {
        seen.push({ user: request.headers.get("x-plg-user"), query: new URL(request.url).search });
        return HttpResponse.json(tasksFixture("digest_S06.json"));
      }),
    );

    const response = await getDigest(
      new NextRequest("http://localhost/api/tasks/digest?staff_id=S06&limit=10", SIGNED_IN),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(tasksFixture("digest_S06.json"));
    expect(seen).toHaveLength(1);
    expect(seen[0].user).toBe("S04");
    expect(Object.fromEntries(new URLSearchParams(seen[0].query))).toEqual({ staff_id: "S06", limit: "10" });
  });

  it("asks for the officer's own tasks when no officer is named", async () => {
    const queries: string[] = [];
    server.use(
      http.get(`${PLG_API}/tasks/digest`, ({ request }) => {
        queries.push(new URL(request.url).search);
        return HttpResponse.json(tasksFixture("digest.json"));
      }),
    );

    const response = await getDigest(new NextRequest("http://localhost/api/tasks/digest", SIGNED_IN));

    expect(response.status).toBe(200);
    expect(queries).toEqual([""]);
  });

  it("relays plg-api's refusal to show another officer's tasks", async () => {
    server.use(
      http.get(`${PLG_API}/tasks/digest`, () =>
        HttpResponse.json({ detail: "Your role can't view this officer's tasks" }, { status: 403 }),
      ),
    );

    const response = await getDigest(new NextRequest("http://localhost/api/tasks/digest?staff_id=S12", SIGNED_IN));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "Your role can't view this officer's tasks" });
  });

  it("relays an unknown officer as 404", async () => {
    server.use(
      http.get(`${PLG_API}/tasks/digest`, () => HttpResponse.json({ detail: "Unknown staff ID" }, { status: 404 })),
    );

    expect((await getDigest(new NextRequest("http://localhost/api/tasks/digest?staff_id=S99", SIGNED_IN))).status).toBe(
      404,
    );
  });

  it("is 422 for a limit that isn't a whole number, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.get(`${PLG_API}/tasks/digest`, () => {
        called = true;
        return HttpResponse.json(tasksFixture("digest.json"));
      }),
    );

    expect((await getDigest(new NextRequest("http://localhost/api/tasks/digest?limit=lots", SIGNED_IN))).status).toBe(
      422,
    );
    expect(called).toBe(false);
  });

  it("is 401 when not signed in, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.get(`${PLG_API}/tasks/digest`, () => {
        called = true;
        return HttpResponse.json(tasksFixture("digest.json"));
      }),
    );

    expect((await getDigest(new NextRequest("http://localhost/api/tasks/digest"))).status).toBe(401);
    expect(called).toBe(false);
  });

  it("is 502 when plg-api is unavailable", async () => {
    server.use(http.get(`${PLG_API}/tasks/digest`, () => HttpResponse.error()));

    expect((await getDigest(new NextRequest("http://localhost/api/tasks/digest", SIGNED_IN))).status).toBe(502);
  });
});

describe("/api/tasks/team", () => {
  it("lists the officers whose tasks the signed-in officer may view", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/tasks/team`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json(tasksFixture("team.json"));
      }),
    );

    const response = await getTeam(new NextRequest("http://localhost/api/tasks/team", SIGNED_IN));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(tasksFixture("team.json"));
    expect(users).toEqual(["S04"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await getTeam(new NextRequest("http://localhost/api/tasks/team"))).status).toBe(401);
  });
});
