"use client";

import { useEffect, useState } from "react";
import type { TaskDigest, UserCtx } from "@/lib/events";
import { TaskList } from "../TaskList";

/** How many tasks the officer can choose to see. */
export const SHOW_COUNTS = [5, 10, 20, 50] as const;

function failure(status: number): string {
  if (status === 403) return "Your role can't view this officer's tasks.";
  if (status === 404) return "That officer could not be found.";
  if (status === 401) return "You are no longer signed in. Sign in again.";
  return "Could not load the tasks.";
}

type Loaded = { key: string; digest: TaskDigest } | { key: string; error: string };

/**
 * The signed-in officer's top open tasks, ranked by urgency × impact. A team lead can switch to a team member's
 * tasks (the officers GET /api/tasks/team allows); the number shown can be changed.
 */
export function TasksScreen() {
  const [team, setTeam] = useState<UserCtx[]>([]);
  const [officer, setOfficer] = useState<string | null>(null);
  const [limit, setLimit] = useState<number>(SHOW_COUNTS[0]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    let current = true;
    fetch("/api/tasks/team")
      .then(async (response) => {
        if (!response.ok) return;
        const found = (await response.json()) as UserCtx[];
        if (current) setTeam(found);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, []);

  const query = new URLSearchParams({ limit: String(limit) });
  if (officer) query.set("staff_id", officer);
  const key = query.toString();

  useEffect(() => {
    let current = true;
    fetch(`/api/tasks/digest?${key}`)
      .then(async (response) => {
        if (!current) return;
        if (!response.ok) return setLoaded({ key, error: failure(response.status) });
        const digest = (await response.json()) as TaskDigest;
        if (current) setLoaded({ key, digest });
      })
      .catch(() => current && setLoaded({ key, error: "Could not load the tasks." }));
    return () => {
      current = false;
    };
  }, [key]);

  const self = team[0]?.staff_id;
  const showing = loaded?.key === key ? loaded : null;

  return (
    <>
      <form aria-label="Tasks shown" onSubmit={(e) => e.preventDefault()}>
        {team.length > 1 && (
          <p>
            <label htmlFor="officer">Officer</label>{" "}
            <select
              id="officer"
              value={officer ?? self}
              onChange={(e) => setOfficer(e.target.value === self ? null : e.target.value)}
            >
              {team.map((member) => (
                <option key={member.staff_id} value={member.staff_id}>
                  {member.staff_id === self ? `${member.name} (you)` : member.name}
                </option>
              ))}
            </select>
          </p>
        )}
        <p>
          <label htmlFor="show">Show</label>{" "}
          <select id="show" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {SHOW_COUNTS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </p>
      </form>
      {!showing && <p role="status">Loading…</p>}
      {showing && "error" in showing && <p role="alert">{showing.error}</p>}
      {showing && "digest" in showing && (
        <TaskList digest={showing.digest} heading={`Top tasks for ${showing.digest.name}`} />
      )}
    </>
  );
}
