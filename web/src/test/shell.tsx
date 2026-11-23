import type { ReactNode } from "react";
import { AppShell } from "@/app/shell/AppShell";
import type { UserCtx } from "@/lib/events";
import type { Theme } from "@/lib/theme";

/** The persona the shell tests sign in as (S05, as in the plg-api tests). */
export const OFFICER: UserCtx = {
  staff_id: "S05",
  name: "Siti Aishah Yusof",
  title: "Senior Estate Officer",
  dept: "Estate Management",
  role: "officer",
  developer: false,
};

/**
 * A screen inside the app shell, as the (shell) layout renders it. Test files mock `next/navigation`
 * (usePathname, useRouter): there is no App Router under Vitest. `theme` = the saved choice the server read.
 */
export function inShell(screen: ReactNode, user: UserCtx = OFFICER, theme?: Theme) {
  return (
    <AppShell user={user} theme={theme}>
      {screen}
    </AppShell>
  );
}
