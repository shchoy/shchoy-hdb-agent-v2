import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/session";
import { CuratorQueue } from "../../memory/CuratorQueue";
import { MemoryScreen } from "../../memory/MemoryScreen";

export const dynamic = "force-dynamic";

export default async function MemoryPage() {
  const user = await currentUser();
  if (!user) redirect("/sign-in");

  return (
    <>
      <h1>What I remember about you</h1>
      <section aria-labelledby="memories-heading">
        <h2 id="memories-heading">Your memories</h2>
        <MemoryScreen />
      </section>
      <CuratorQueue staffId={user.staff_id} />
    </>
  );
}
