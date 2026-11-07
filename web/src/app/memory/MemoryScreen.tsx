"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/api/schema";

type Memory = components["schemas"]["MemoryView"];

/** The officer's own memories: where each came from, and controls to edit, keep or forget it. */
export function MemoryScreen() {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);

  const [version, setVersion] = useState(0);

  useEffect(() => {
    let current = true;
    fetch("/api/memory")
      .then(async (response) => {
        if (!current) return;
        if (!response.ok) return setError("Could not load your memories.");
        setError(null);
        setMemories((await response.json()) as Memory[]);
      })
      .catch(() => current && setError("Could not load your memories."));
    return () => {
      current = false;
    };
  }, [version]);

  async function change(id: string, init: RequestInit) {
    const response = await fetch(`/api/memory/${id}`, init);
    if (!response.ok) return setError("That change did not go through.");
    setEditing(null);
    setVersion((v) => v + 1);
  }

  const patch = (id: string, body: object) =>
    change(id, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

  if (error) return <p role="alert">{error}</p>;
  if (!memories) return <p>Loading…</p>;
  if (memories.length === 0) return <p>Nothing remembered yet.</p>;

  return (
    <ul aria-label="Memories">
      {memories.map((m) => (
        <li key={m.id}>
          {editing?.id === m.id ? (
            <>
              <label>
                Memory text
                <input
                  value={editing.text}
                  onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                />
              </label>
              <button type="button" onClick={() => patch(m.id, { text: editing.text })}>
                Save
              </button>
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <p>
                <strong>{m.kind}</strong>: {m.text}
              </p>
              <p>
                From: {m.provenance}
                {m.expires_at ? ` · expires ${new Date(m.expires_at).toLocaleDateString("en-SG")}` : ""}
              </p>
              {m.status === "pending_review" && (
                <p role="status">
                  Flagged: this conflicts with current policy, so it is not being used. Edit it to make the
                  exception clear, or forget it.
                </p>
              )}
              <button type="button" onClick={() => setEditing({ id: m.id, text: m.text })}>
                Edit
              </button>
              <button type="button" onClick={() => change(m.id, { method: "DELETE" })}>
                Forget
              </button>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
