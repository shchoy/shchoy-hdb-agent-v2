"use client";

import {
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import type { components } from "@/lib/api/schema";
import { answerAsText } from "./copyText";
import type { Cited } from "./SourcesPanel";
import { TraceLink } from "./TraceLink";
import styles from "./ask.module.css";

type Receipt = components["schemas"]["FeedbackReceipt"];
type Sending =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "sent"; receipt: Receipt }
  | { status: "failed"; reason: string };

const ITEMS = "button:not(:disabled), a[href]";

function itemsOf(bar: Element | null): HTMLElement[] {
  return [...(bar?.querySelectorAll<HTMLElement>(ITEMS) ?? [])];
}

/** Toolbar keys: arrows move along the bar (wrapping), Home/End to its ends. */
function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  const items = itemsOf(event.currentTarget);
  const at = items.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  const next = {
    ArrowRight: at + 1,
    ArrowLeft: at - 1,
    Home: 0,
    End: items.length - 1,
  }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  items[(next + items.length) % items.length].focus();
}

/**
 * The ARIA toolbar pattern's single Tab stop: the item last focused, else the first. Items come and go (feedback
 * sent, a trace link), so tabindex is re-applied after every render and on every focus inside the bar.
 */
function rove(bar: Element | null, current: Element | null) {
  const items = itemsOf(bar);
  const active = items.find((item) => item === current) ?? items[0];
  for (const item of items) item.tabIndex = item === active ? 0 : -1;
}

/**
 * The bar that ends every answer with a run: Copy (plain text with its sources), 👍 / 👎 feedback (a 👎 asks what
 * the answer should have said and, optionally, a team fact it missed: both go to the curators for review, never
 * straight into use) and, for developers, View trace.
 */
export function AnswerActions({
  threadId,
  runId,
  markdown,
  citations,
  developer,
}: {
  threadId: string;
  runId: string;
  markdown: string;
  citations: Cited[];
  developer: boolean;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const focused = useRef<Element | null>(null);
  const copyButton = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => rove(bar.current, focused.current));
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const [state, setState] = useState<Sending>({ status: "idle" });
  const [open, setOpen] = useState(false);
  const [correction, setCorrection] = useState("");
  const [teamFact, setTeamFact] = useState("");
  const [comment, setComment] = useState("");
  const sending = state.status === "sending";

  async function copyAnswer() {
    setCopy("idle"); // cleared first, so a second copy is announced again
    try {
      await navigator.clipboard.writeText(answerAsText(markdown, citations));
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  async function send(body: Record<string, string>) {
    // 👍 / 👎 leave the bar once sent: focus then moves to Copy rather than dropping to the page.
    const fromBar = bar.current?.contains(document.activeElement) ?? false;
    setState({ status: "sending" });
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, run_id: runId, ...body }),
      });
      const json = (await response.json().catch(() => null)) as
        (Receipt & { detail?: unknown }) | null;
      if (!response.ok || !json) {
        const detail = json?.detail;
        return setState({
          status: "failed",
          reason:
            typeof detail === "string"
              ? detail
              : "Your feedback did not go through.",
        });
      }
      setState({ status: "sent", receipt: json });
      if (fromBar) setTimeout(() => copyButton.current?.focus());
    } catch {
      setState({
        status: "failed",
        reason: "Could not reach the server. Try again.",
      });
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send({
      score: "down",
      correction: correction.trim(),
      team_fact: teamFact.trim(),
      comment: comment.trim(),
    });
  }

  const proposals =
    state.status === "sent" ? state.receipt.proposals.length : 0;

  return (
    <div className={styles.actions}>
      <div className={styles.actionRow}>
        <div
          role="toolbar"
          aria-label="Answer actions"
          className={styles.actionBar}
          ref={bar}
          onFocus={(event) => {
            if (!itemsOf(event.currentTarget).includes(event.target)) return;
            focused.current = event.target;
            rove(event.currentTarget, event.target);
          }}
          onKeyDown={moveFocus}
        >
          <button
            ref={copyButton}
            type="button"
            onClick={() => void copyAnswer()}
            onBlur={() => setCopy("idle")}
          >
            Copy
          </button>
          {state.status !== "sent" && (
            <>
              <button
                type="button"
                aria-label="Helpful"
                disabled={sending}
                onClick={() => void send({ score: "up" })}
              >
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
            </>
          )}
          {developer && <TraceLink threadId={threadId} runId={runId} />}
        </div>
        <span role="status" className={styles.hint}>
          {copy === "copied"
            ? "Copied"
            : copy === "failed"
              ? "Could not copy. Select the answer and copy it by hand."
              : ""}
        </span>
      </div>
      {state.status === "sent" && (
        <p
          role="status"
          aria-label="Feedback sent"
          className={styles.feedbackSent}
        >
          Thanks — sent for review.
          {proposals > 0 &&
            ` ${proposals} proposal${proposals === 1 ? "" : "s"} waiting for a curator.`}
        </p>
      )}
      {open && state.status !== "sent" && (
        <form onSubmit={onSubmit} className={styles.feedbackForm}>
          <label>
            Correct this
            <textarea
              rows={3}
              value={correction}
              onChange={(e) => setCorrection(e.target.value)}
            />
          </label>
          <label>
            Team fact (optional)
            <textarea
              rows={2}
              value={teamFact}
              onChange={(e) => setTeamFact(e.target.value)}
            />
          </label>
          <label>
            Comment (optional)
            <textarea
              rows={2}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
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
