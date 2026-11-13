import Link from "next/link";
import { redirect } from "next/navigation";
import { roleLabel } from "@/lib/events";
import { currentUser } from "@/lib/server/session";
import { SignOutButton } from "../SignOutButton";
import { ApprovalsScreen } from "./ApprovalsScreen";

export const dynamic = "force-dynamic";

export default async function ApprovalsPage() {
  const user = await currentUser();
  if (!user) redirect("/sign-in");

  return (
    <>
      <header className="banner">
        <p>
          Signed in as <strong>{user.name}</strong> ({roleLabel(user.role)})
        </p>
        <Link href="/">Ask</Link>
        <Link href="/memory">Memory</Link>
        <Link href="/doc-check">Document check</Link>
        <SignOutButton />
      </header>
      <main>
        <h1>Approvals</h1>
        <ApprovalsScreen role={user.role} />
      </main>
    </>
  );
}
