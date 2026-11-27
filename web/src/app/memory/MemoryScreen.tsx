"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/api/schema";
import { Badge, Card, cardListClass } from "../Card";
import { dateOf } from "../dates";
import { FoundLabel, useFound } from "../found";
import styles from "./memory.module.css";

type Memory = components["schemas"]["MemoryView"];

const MEMORY_KIND: Record<string, string> = { profile: "Profile", preference: "Preference", episode: "Past work" };

/**
 * The officer's own memories: where each came from, and controls to edit or forget it. `found` (#109): the memory a
 * search result opened the screen at: highlighted, scrolled to and focused.
 */
export function MemoryScreen({ found = null }: { found?: string | null }) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);

  const [version, setVersion] = useState(0);
  const foundProps = useFound<HTMLLIElement>(found);

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
  const gone = found != null && !memories.some((m) => m.id === found);
  const notice = gone && <p role="status">That memory is no longer here: it may have been forgotten.</p>;
  if (memories.length === 0) return notice || <p>Nothing remembered yet.</p>;

  return (
    <>
      {notice}
      <ul aria-label="Memories" className={cardListClass}>
        {memories.map((m) => {
          const flagged = m.status === "pending_review";
          return (
            <li key={m.id} {...foundProps(m.id)}>
              <FoundLabel found={m.id === found} />
              <Card
                as="article"
                heading={MEMORY_KIND[m.kind] ?? m.kind}
                badges={flagged && <Badge tone="warning">Not in use</Badge>}
              >
                {editing?.id === m.id ? (
                  <div className={styles.form}>
                    <label>
                      Memory text
                      <textarea
                        rows={3}
                        value={editing.text}
                        onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                      />
                    </label>
                    <div className={styles.actions}>
                      <button type="button" onClick={() => patch(m.id, { text: editing.text })}>
                        Save
                      </button>
                      <button type="button" onClick={() => setEditing(null)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className={styles.text}>{m.text}</p>
                    <p className={styles.meta}>
                      From: {m.provenance}
                      {m.expires_at ? ` · expires ${dateOf(m.expires_at)}` : ""}
                    </p>
                    {flagged && (
                      <p role="status" className={styles.flag}>
                        Flagged: this conflicts with current policy, so it is not being used. Edit it to make the
                        exception clear, or forget it.
                      </p>
                    )}
                    <div className={styles.actions}>
                      <button type="button" onClick={() => setEditing({ id: m.id, text: m.text })}>
                        Edit
                      </button>
                      <button type="button" data-variant="danger" onClick={() => change(m.id, { method: "DELETE" })}>
                        Forget
                      </button>
                    </div>
                  </>
              )}
            </Card>
          </li>
          );
        })}
      </ul>
    </>
  );
}
