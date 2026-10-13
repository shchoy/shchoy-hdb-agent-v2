import { redirect } from "next/navigation";
import { roleLabel } from "@/lib/events";
import { currentUser } from "@/lib/server/session";
import { AskScreen } from "./AskScreen";
import { SignOutButton } from "./SignOutButton";

export const dynamic = "force-dynamic";

export default async function AskPage() {
  const user = await currentUser();
  if (!user) redirect("/sign-in");

  return (
    <>
      <header className="banner">
        <p>
          Signed in as <strong>{user.name}</strong> ({roleLabel(user.role)})
        </p>
        <SignOutButton />
      </header>
      <main>
        <h1>Ask the Super-Librarian</h1>
        <AskScreen />
      </main>
    </>
  );
}
