// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/uploads/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";
import { uploadFixture, uploadRefusedFixture } from "@/test/sse";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const NOTE = "Site visit notes\nThe estate officer agreed a follow-up visit.\n";

function upload(filename: string | null, cookie?: string, body: BodyInit = NOTE) {
  const query = filename === null ? "" : `?${new URLSearchParams({ filename })}`;
  return POST(
    new NextRequest(`http://localhost/api/uploads${query}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", ...(cookie ? { cookie } : {}) },
      body,
    }),
  );
}

describe("POST /api/uploads", () => {
  it("streams the file's bytes to plg-api as the signed-in user and relays the upload", async () => {
    const seen: { user: string | null; filename: string | null; type: string | null; body: string }[] = [];
    server.use(
      http.post(`${PLG_API}/uploads`, async ({ request }) => {
        seen.push({
          user: request.headers.get("x-plg-user"),
          filename: new URL(request.url).searchParams.get("filename"),
          type: request.headers.get("content-type"),
          body: await request.text(),
        });
        return HttpResponse.json(uploadFixture(), { status: 201 });
      }),
    );

    const response = await upload("site visit.txt", "plg_user=S05");

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(uploadFixture());
    expect(seen).toEqual([{ user: "S05", filename: "site visit.txt", type: "application/octet-stream", body: NOTE }]);
  });

  it("relays plg-api's refusal with its status and detail", async () => {
    const refused = uploadRefusedFixture();
    server.use(http.post(`${PLG_API}/uploads`, () => HttpResponse.json(refused.body, { status: refused.status })));

    const response = await upload("budget.xlsx", "plg_user=S05");

    expect(response.status).toBe(415);
    expect(await response.json()).toEqual(refused.body);
  });

  it("relays a file too large (413)", async () => {
    server.use(
      http.post(`${PLG_API}/uploads`, () =>
        HttpResponse.json({ detail: "big.txt is larger than 20 MB, the most one file may be." }, { status: 413 }),
      ),
    );

    const response = await upload("big.txt", "plg_user=S05");

    expect(response.status).toBe(413);
    expect((await response.json()).detail).toMatch("20 MB");
  });

  it("is 401 when not signed in and 400 without a filename, without calling plg-api", async () => {
    let called = false;
    server.use(
      http.post(`${PLG_API}/uploads`, () => {
        called = true;
        return HttpResponse.json(uploadFixture(), { status: 201 });
      }),
    );

    expect((await upload("note.txt")).status).toBe(401);
    expect((await upload(null, "plg_user=S05")).status).toBe(400);
    expect(called).toBe(false);
  });

  it("is 502 when plg-api is unreachable", async () => {
    server.use(http.post(`${PLG_API}/uploads`, () => HttpResponse.error()));

    expect((await upload("note.txt", "plg_user=S05")).status).toBe(502);
  });
});

describe("GET /api/uploads", () => {
  it("relays the signed-in officer's own uploads", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/uploads`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json([uploadFixture()]);
      }),
    );

    const response = await GET(new NextRequest("http://localhost/api/uploads", { headers: { cookie: "plg_user=S05" } }));

    expect(await response.json()).toEqual([uploadFixture()]);
    expect(users).toEqual(["S05"]);
  });

  it("is 401 when not signed in", async () => {
    expect((await GET(new NextRequest("http://localhost/api/uploads"))).status).toBe(401);
  });
});
