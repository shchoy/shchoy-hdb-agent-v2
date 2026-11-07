import { http, HttpResponse } from "msw";
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET as getFile } from "@/app/api/drafts/[id]/file/route";
import { server } from "@/test/msw";
import { PLG_API } from "@/test/plg-api";

beforeEach(() => vi.stubEnv("PLG_API_URL", PLG_API));

const request = (path: string, cookie?: string) =>
  new NextRequest(`http://localhost${path}`, { headers: cookie ? { cookie } : {} });

describe("GET /api/drafts/{id}/file", () => {
  it("streams the DOCX as the signed-in user, as a download", async () => {
    const users: (string | null)[] = [];
    server.use(
      http.get(`${PLG_API}/drafts/d1/file`, ({ request }) => {
        users.push(request.headers.get("x-plg-user"));
        return new HttpResponse("PK-docx", {
          headers: {
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "content-disposition": 'attachment; filename="TPL-REM-01_d1.docx"',
            "set-cookie": "leak=1",
          },
        });
      }),
    );

    const response = await getFile(request("/api/drafts/d1/file", "plg_user=S05"), {
      params: Promise.resolve({ id: "d1" }),
    });

    expect(await response.text()).toBe("PK-docx");
    expect(users).toEqual(["S05"]);
    expect(response.headers.get("content-disposition")).toContain("attachment");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("is 401 when not signed in", async () => {
    const response = await getFile(request("/api/drafts/d1/file"), { params: Promise.resolve({ id: "d1" }) });

    expect(response.status).toBe(401);
  });

  it("passes on plg-api's 404 for a draft that isn't the user's", async () => {
    server.use(http.get(`${PLG_API}/drafts/d1/file`, () => HttpResponse.json({ detail: "Draft not found" }, { status: 404 })));

    const response = await getFile(request("/api/drafts/d1/file", "plg_user=S04"), {
      params: Promise.resolve({ id: "d1" }),
    });

    expect(response.status).toBe(404);
  });
});
