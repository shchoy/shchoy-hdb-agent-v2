import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/session";
import { ApprovalsScreen } from "../../approvals/ApprovalsScreen";

export const dynamic = "force-dynamic";

export default async function ApprovalsPage() {
  const user = await currentUser();
  if (!user) redirect("/sign-in");

  return (
    <>
      <h1>Approvals</h1>
      <ApprovalsScreen role={user.role} staffId={user.staff_id} />
    </>
  );
}
