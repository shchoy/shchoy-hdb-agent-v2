"use client";

import { useState, type FormEvent } from "react";
import type { components } from "@/lib/api/schema";
import styles from "./ask.module.css";

type Receipt = components["schemas"]["FeedbackReceipt"];
type Sending = { status: "idle" } | { status: "sending" } | { status: "sent"; receipt: Receipt } | { status: "failed"; reason: string };

/**
 * 👍 / 👎 on one answer, named by the run that answered it. A 👎 asks what the answer should have said and,
 * optionally, a team fact the answer missed: both go to the curators for review, never straight into use.
 */
export function AnswerFeedback({ threadId, runId }: { threadId: string; runId: string }) {
  const [state, setState] = useState<Sending>({ status: "idle" });
  const [open, setOpen] = useState(false);
  const [correction, setCorrection] = useState("");
  const [teamFact, setTeamFact] = useState("");
  const [comment, setComment] = useState("");
  const sending = state.status === "sending";

  async function send(body: Record<string, string>) {
    setState({ status: "sending" });
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, run_id: runId, ...body }),
      });
      const json = (await response.json().catch(() => null)) as (Receipt & { detail?: unknown }) | null;
      if (!response.ok || !json) {
        const detail = json?.detail;
        return setState({ status: "failed", reason: typeof detail === "string" ? detail : "Your feedback did not go through." });
      }
      setState({ status: "sent", receipt: json });
    } catch {
      setState({ status: "failed", reason: "Could not reach the server. Try again." });
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send({ score: "down", correction: correction.trim(), team_fact: teamFact.trim(), comment: comment.trim() });
  }

  if (state.status === "sent") {
    const n = state.receipt.proposals.length;
    return (
      <p role="status" aria-label="Feedback sent" className={styles.feedback}>
        Thanks — sent for review.
        {n > 0 && ` ${n} proposal${n === 1 ? "" : "s"} waiting for a curator.`}
      </p>
    );
  }

  return (
    <div className={styles.feedback}>
      <button type="button" aria-label="Helpful" disabled={sending} onClick={() => void send({ score: "up" })}>
        👍
      </button>
      <button
        type="button"
        aria-label="Not helpful"
        aria-expanded={open}
        disabled={sending}
        onClick={() => setOpen((o) => !o)}
      >
        👎
      </button>
      {open && (
        <form onSubmit={onSubmit} className={styles.feedbackForm}>
          <label>
            Correct this
            <textarea rows={3} value={correction} onChange={(e) => setCorrection(e.target.value)} />
          </label>
          <label>
            Team fact (optional)
            <textarea rows={2} value={teamFact} onChange={(e) => setTeamFact(e.target.value)} />
          </label>
          <label>
            Comment (optional)
            <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <button type="submit" disabled={sending}>
            Send
          </button>
        </form>
      )}
      {state.status === "failed" && <p role="alert">{state.reason}</p>}
    </div>
  );
}
