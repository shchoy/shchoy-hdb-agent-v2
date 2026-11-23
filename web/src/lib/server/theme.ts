import "server-only";
import { cookies } from "next/headers";
import { savedTheme, THEME_COOKIE, type Theme } from "@/lib/theme";

/** The theme the officer chose, for server components; undefined = follow the OS. */
export async function currentTheme(): Promise<Theme | undefined> {
  return savedTheme((await cookies()).get(THEME_COOKIE)?.value);
}
