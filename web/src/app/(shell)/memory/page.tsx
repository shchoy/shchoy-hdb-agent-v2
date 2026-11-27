import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/session";
import { foundParam } from "../../foundParam";
import { CuratorQueue } from "../../memory/CuratorQueue";
import { MemoryScreen } from "../../memory/MemoryScreen";

export const dynamic = "force-dynamic";

export default async function MemoryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await currentUser();
  if (!user) redirect("/sign-in");
  const found = foundParam(await searchParams); // a search result opened it at this item (#109)

  return (
    <>
      <h1>What I remember about you</h1>
      <section aria-labelledby="memories-heading">
        <h2 id="memories-heading">Your memories</h2>
        <MemoryScreen found={found} />
      </section>
      <CuratorQueue staffId={user.staff_id} />
    </>
  );
}
