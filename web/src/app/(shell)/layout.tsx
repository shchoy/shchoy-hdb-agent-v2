import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { currentUser } from "@/lib/server/session";
import { currentTheme } from "@/lib/server/theme";
import { AppShell } from "../shell/AppShell";

export const dynamic = "force-dynamic";

/** Every signed-in screen sits in the one app shell (sidebar + screen); signed out, it is the sign-in page. */
export default async function ShellLayout({ children }: { children: ReactNode }) {
  const user = await currentUser();
  if (!user) redirect("/sign-in");
  return (
    <AppShell user={user} theme={await currentTheme()}>
      {children}
    </AppShell>
  );
}
