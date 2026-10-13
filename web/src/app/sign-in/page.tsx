import type { Metadata } from "next";
import { listPersonas } from "@/lib/server/plg-api";
import { SignInForm } from "./SignInForm";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sign in · PLG Super-Librarian" };

export default async function SignInPage() {
  const personas = await listPersonas();
  return (
    <main>
      <h1>Sign in</h1>
      <p>Proof of concept: choose a staff persona to sign in as.</p>
      <SignInForm personas={personas} />
    </main>
  );
}
