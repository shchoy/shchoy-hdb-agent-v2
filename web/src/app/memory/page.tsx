import Link from "next/link";
import { redirect } from "next/navigation";
import { roleLabel } from "@/lib/events";
import { currentUser } from "@/lib/server/session";
import { SignOutButton } from "../SignOutButton";
import { CuratorQueue } from "./CuratorQueue";
import { MemoryScreen } from "./MemoryScreen";

export const dynamic = "force-dynamic";

export default async function MemoryPage() {
  const user = await currentUser();
  if (!user) redirect("/sign-in");

  return (
    <>
      <header className="banner">
        <p>
          Signed in as <strong>{user.name}</strong> ({roleLabel(user.role)})
        </p>
        <Link href="/">Ask</Link>
        <Link href="/approvals">Approvals</Link>
        <Link href="/doc-check">Document check</Link>
        <Link href="/tasks">Tasks</Link>
        <Link href="/library">Library</Link>
        <SignOutButton />
      </header>
      <main>
        <h1>What I remember about you</h1>
        <MemoryScreen />
        <CuratorQueue staffId={user.staff_id} />
      </main>
    </>
  );
}
