/** Mock sign-in session: the chosen persona's staff ID in an httpOnly cookie. */
import "server-only";
import { cookies } from "next/headers";
import type { NextRequest, NextResponse } from "next/server";
import { getMe, type UserCtx } from "@/lib/server/plg-api";

export const SESSION_COOKIE = "plg_user";

export function setSession(response: NextResponse, staffId: string): void {
  response.cookies.set(SESSION_COOKIE, staffId, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
  });
}

export function clearSession(response: NextResponse): void {
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
    maxAge: 0,
  });
}

/** Staff ID from the session cookie of a route handler request. */
export function sessionStaffId(request: NextRequest): string | undefined {
  return request.cookies.get(SESSION_COOKIE)?.value || undefined;
}

/** The signed-in user for a server component, or null if absent or unknown to plg-api. */
export async function currentUser(): Promise<UserCtx | null> {
  const staffId = (await cookies()).get(SESSION_COOKIE)?.value;
  return staffId ? getMe(staffId) : null;
}
