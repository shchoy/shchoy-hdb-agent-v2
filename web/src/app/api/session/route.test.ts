// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DELETE, POST } from "@/app/api/session/route";
import { server } from "@/test/msw";
import { PLG_API, personasApi } from "@/test/plg-api";

function signIn(body: unknown): Promise<Response> {
  return POST(
    new NextRequest("http://localhost/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

beforeEach(() => {
  vi.stubEnv("PLG_API_URL", PLG_API);
  server.use(personasApi);
});

describe("POST /api/session", () => {
  it("sets an httpOnly plg_user cookie for a known persona", async () => {
    const response = await signIn({ staff_id: "S04" });

    expect(response.status).toBe(204);
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toMatch(/^plg_user=S04;/);
    expect(cookie).toMatch(/HttpOnly/i);
    expect(cookie).toMatch(/SameSite=lax/i);
    expect(cookie).toMatch(/Path=\//);
  });

  it("rejects an unknown persona without setting a cookie", async () => {
    const response = await signIn({ staff_id: "S99" });

    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("rejects a request without a staff ID", async () => {
    const response = await signIn({});

    expect(response.status).toBe(400);
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});

describe("DELETE /api/session", () => {
  it("clears the plg_user cookie", async () => {
    const response = await DELETE();

    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toMatch(/^plg_user=;.*(Max-Age=0|Expires=Thu, 01 Jan 1970)/i);
  });
});
