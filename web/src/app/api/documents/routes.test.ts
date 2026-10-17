// @vitest-environment node
import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as getChunk } from "@/app/api/documents/[id]/chunks/[chunkId]/route";
import { GET as getFile } from "@/app/api/documents/[id]/file/route";
import { GET as getDocument } from "@/app/api/documents/[id]/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const request = (path: string, cookie?: string) =>
  new NextRequest(`http://localhost${path}`, { headers: cookie ? { cookie } : {} });

describe("GET /api/documents/{id}", () => {
  it("relays the document as the signed-in user", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/documents/SP-1`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return HttpResponse.json({ doc_id: "SP-1" });
      }),
    );

    const response = await getDocument(request("/api/documents/SP-1", "plg_user=S04"), {
      params: Promise.resolve({ id: "SP-1" }),
    });

    expect(await response.json()).toEqual({ doc_id: "SP-1" });
    expect(users).toEqual(["S04"]);
  });

  it("is 401 when not signed in, 404 when plg-api has no such document", async () => {
    const params = { params: Promise.resolve({ id: "NOPE" }) };
    server.use(
      http.get(`${PLG_API}/documents/NOPE`, () => HttpResponse.json({ detail: "Document not found" }, { status: 404 })),
    );

    expect((await getDocument(request("/api/documents/NOPE"), params)).status).toBe(401);
    expect((await getDocument(request("/api/documents/NOPE", "plg_user=S04"), params)).status).toBe(404);
  });
});

describe("GET /api/documents/{id}/chunks/{chunkId}", () => {
  it("relays the cited span's location, passing the span and encoding the chunk ID", async () => {
    const seen: string[] = [];
    server.use(
      http.get(`${PLG_API}/documents/SP-1/chunks/:chunk`, ({ request }) => {
        seen.push(new URL(request.url).pathname + new URL(request.url).search);
        return HttpResponse.json({ chunk_id: "SP-1#002" });
      }),
    );

    const response = await getChunk(request("/api/documents/SP-1/chunks/SP-1%23002?start=3&end=40", "plg_user=S04"), {
      params: Promise.resolve({ id: "SP-1", chunkId: "SP-1#002" }),
    });

    expect(await response.json()).toEqual({ chunk_id: "SP-1#002" });
    expect(seen).toEqual(["/documents/SP-1/chunks/SP-1%23002?start=3&end=40"]);
  });

  it("is 401 when not signed in", async () => {
    const response = await getChunk(request("/api/documents/SP-1/chunks/c"), {
      params: Promise.resolve({ id: "SP-1", chunkId: "c" }),
    });

    expect(response.status).toBe(401);
  });
});

describe("GET /api/documents/{id}/file", () => {
  it("streams the file with plg-api's safety headers", async () => {
    server.use(
      http.get(`${PLG_API}/documents/SP-1/file`, () =>
        new HttpResponse("%PDF-1.7", {
          headers: {
            "content-type": "application/pdf",
            "content-disposition": 'inline; filename="a.pdf"',
            "x-content-type-options": "nosniff",
            "content-security-policy": "sandbox",
            "set-cookie": "leak=1",
          },
        }),
      ),
    );

    const response = await getFile(request("/api/documents/SP-1/file", "plg_user=S04"), {
      params: Promise.resolve({ id: "SP-1" }),
    });

    expect(await response.text()).toBe("%PDF-1.7");
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toBe('inline; filename="a.pdf"');
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-security-policy")).toBe("sandbox");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("is 401 when not signed in", async () => {
    const response = await getFile(request("/api/documents/SP-1/file"), { params: Promise.resolve({ id: "SP-1" }) });

    expect(response.status).toBe(401);
  });
});
