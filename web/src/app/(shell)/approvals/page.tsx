import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/session";
import { foundParam } from "../../foundParam";
import { ApprovalsScreen } from "../../approvals/ApprovalsScreen";

export const dynamic = "force-dynamic";

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await currentUser();
  if (!user) redirect("/sign-in");
  const found = foundParam(await searchParams); // a search result opened it at this item (#109)

  return (
    <>
      <h1>Approvals</h1>
      <ApprovalsScreen role={user.role} staffId={user.staff_id} found={found} />
    </>
  );
}
