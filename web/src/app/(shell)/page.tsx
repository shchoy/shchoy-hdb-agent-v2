import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/session";
import { AskScreen } from "../AskScreen";

export const dynamic = "force-dynamic";

export default async function AskPage() {
  const user = await currentUser();
  if (!user) redirect("/sign-in");

  return (
    <>
      <h1>Ask the Super-Librarian</h1>
      <AskScreen developer={user.developer} user={user} />
    </>
  );
}
