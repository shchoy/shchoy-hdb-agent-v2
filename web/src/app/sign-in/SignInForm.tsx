"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { roleLabel, type UserCtx } from "@/lib/events";
import styles from "./sign-in.module.css";

export function SignInForm({ personas }: { personas: UserCtx[] }) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function signIn(staffId: string) {
    setPending(staffId);
    setFailed(false);
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ staff_id: staffId }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      router.push("/");
      router.refresh();
    } catch {
      setFailed(true);
      setPending(null);
    }
  }

  return (
    <>
      {failed && (
        <p role="alert" className={styles.alert}>
          We could not sign you in. Please try again.
        </p>
      )}
      <ul className={styles.personas}>
        {personas.map((p) => (
          <li key={p.staff_id}>
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => void signIn(p.staff_id)}
              className={styles.persona}
            >
              <span className={styles.name}>{p.name}</span>
              <span>{p.title}</span>
              <span className={styles.role}>{roleLabel(p.role)}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
