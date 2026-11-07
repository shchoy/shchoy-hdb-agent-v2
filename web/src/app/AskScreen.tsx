"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import {
  InvalidFrameError,
  parseRunEvents,
  type CitationEvent,
  type DraftEvent,
  type PolicyStanceEvent,
  type ThreadSummary,
  type ThreadView,
} from "@/lib/events";
import { DraftPreview } from "./DraftPreview";
import { PolicyStanceCard } from "./PolicyStanceCard";
import { SourceViewer } from "./SourceViewer";
import styles from "./ask.module.css";

type Step = { node: string; finished: boolean };

type Answer = {
  question: string;
  answer: string;
  citations: CitationEvent[];
  drafts: DraftEvent[];
  stances: PolicyStanceEvent[];
  trajectory: Step[];
};

type Run =
  | { status: "idle" }
  | ({ status: "running" } & Answer)
  | ({ status: "done" } & Answer)
  | { status: "failed"; question: string; reason: string; trajectory: Step[] };

/** The run failed or was cut short: whatever was streamed is partial and not to be trusted. */
class RunFailed extends Error {}

async function createThread(): Promise<string> {
  const response = await fetch("/api/threads", { method: "POST" });
  if (!response.ok) throw new RunFailed(failureFor(response.status));
  const { thread_id } = (await response.json()) as { thread_id: string };
  return thread_id;
}

function failureFor(status: number): string {
  return status === 401
    ? "You are no longer signed in. Sign in again, then retry."
    : `The service responded with an error (HTTP ${status}).`;
}

const RESUME_ATTEMPTS = 3;
const ACTIVE_THREAD = "plg_active_thread";

/** The run's stream stopped before `done`; it may be picked up again from the last event seen. */
class Interrupted extends Error {}

export function AskScreen() {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<Run>({ status: "idle" });
  const [history, setHistory] = useState<ThreadView["messages"]>([]);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const threadId = useRef<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const running = run.status === "running";

  async function refreshThreads() {
    const response = await fetch("/api/threads").catch(() => null);
    if (response?.ok) setThreads((await response.json()) as ThreadSummary[]);
  }

  /** Reads one run to its end, from whatever stream `open` gives. Resumes after a dropped connection. */
  async function follow(
    text: string,
    open: (lastSeq: number) => Promise<Response>,
    prior?: Answer,
  ) {
    const acc: Answer = prior ?? {
      question: text,
      answer: "",
      citations: [],
      drafts: [],
      stances: [],
      trajectory: [],
    };
    let lastSeq = 0;
    const update = (status: "running" | "done") => setRun({ status, ...acc });
    update("running");
    try {
      for (let attempt = 0; ; attempt++) {
        try {
          const response = await open(lastSeq);
          if (response.status !== 200 || !response.body)
            throw new RunFailed(failureFor(response.status));
          for await (const event of parseRunEvents(response.body)) {
            lastSeq = event.seq;
            switch (event.type) {
              case "node":
                acc.trajectory =
                  event.status === "started"
                    ? [...acc.trajectory, { node: event.node, finished: false }]
                    : acc.trajectory.map((step) =>
                        step.node === event.node && !step.finished
                          ? { ...step, finished: true }
                          : step,
                      );
                break;
              case "token":
                acc.answer += event.text;
                break;
              case "citation":
                acc.citations = [...acc.citations, event];
                break;
              case "draft":
                acc.drafts = [...acc.drafts, event];
                break;
              case "policy_stance":
                acc.stances = [...acc.stances, event];
                break;
              case "error":
                throw new RunFailed(event.message);
              case "done":
                update("done");
                void refreshThreads();
                return;
            }
            update("running");
          }
          throw new Interrupted();
        } catch (error) {
          const resumable =
            error instanceof Interrupted ||
            !(error instanceof RunFailed || error instanceof InvalidFrameError);
          if (!resumable || attempt >= RESUME_ATTEMPTS || !threadId.current)
            throw error;
          // Reconnect from the last event seen; the run carried on without us.
          const id = threadId.current;
          const from = String(lastSeq);
          open = (seq) =>
            fetch(`/api/threads/${encodeURIComponent(id)}/runs/latest`, {
              headers: {
                Accept: "text/event-stream",
                "Last-Event-ID": String(seq || from),
              },
            });
          await new Promise((resolve) =>
            setTimeout(resolve, 100 * (attempt + 1)),
          );
        }
      }
    } catch (error) {
      const reason =
        error instanceof RunFailed
          ? error.message
          : error instanceof Interrupted
            ? "The connection closed before the answer was complete."
            : "The answer could not be received. Check your connection.";
      setRun({
        status: "failed",
        question: acc.question,
        reason,
        trajectory: acc.trajectory,
      });
    }
  }

  async function ask(text: string) {
    if (run.status === "done") {
      setHistory((h) => [
        ...h,
        { role: "user", content: run.question },
        { role: "assistant", content: run.answer },
      ]);
    }
    setRun({
      status: "running",
      question: text,
      answer: "",
      citations: [],
      drafts: [],
      stances: [],
      trajectory: [],
    });
    try {
      if (threadId.current === null) {
        threadId.current = await createThread();
        sessionStorage.setItem(ACTIVE_THREAD, threadId.current);
        setActive(threadId.current);
      }
    } catch (error) {
      const reason =
        error instanceof RunFailed
          ? error.message
          : "The answer could not be received. Check your connection.";
      setRun({ status: "failed", question: text, reason, trajectory: [] });
      return;
    }
    const id = threadId.current;
    await follow(text, () =>
      fetch(`/api/threads/${encodeURIComponent(id)}/runs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ message: text }),
      }),
    );
  }

  /** Opens a past conversation; if its last question is still being answered, picks that answer up. */
  async function open(id: string) {
    const response = await fetch(
      `/api/threads/${encodeURIComponent(id)}`,
    ).catch(() => null);
    if (!response?.ok) {
      sessionStorage.removeItem(ACTIVE_THREAD);
      return;
    }
    const thread = (await response.json()) as ThreadView;
    threadId.current = id;
    setActive(id);
    sessionStorage.setItem(ACTIVE_THREAD, id);
    setHistory(thread.messages);
    setRun({ status: "idle" });
    if (thread.running) {
      await follow(thread.running, () =>
        fetch(`/api/threads/${encodeURIComponent(id)}/runs/latest`, {
          headers: { Accept: "text/event-stream" },
        }),
      );
    }
  }

  function startNew() {
    if (running) return;
    threadId.current = null;
    setActive(null);
    sessionStorage.removeItem(ACTIVE_THREAD);
    setHistory([]);
    setRun({ status: "idle" });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshThreads();
    const active = sessionStorage.getItem(ACTIVE_THREAD);
    if (active) void open(active);
    // Runs once on load: a refresh returns to the conversation (and answer) it interrupted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || running) return;
    setQuestion("");
    void ask(text);
  }

  return (
    <div className={styles.layout}>
      <nav aria-label="Conversations" className={styles.threads}>
        <button type="button" onClick={startNew} disabled={running}>
          New conversation
        </button>
        <ul>
          {threads.map((t) => (
            <li key={t.thread_id}>
              <button
                type="button"
                disabled={running}
                aria-current={t.thread_id === active ? "true" : undefined}
                onClick={() => void open(t.thread_id)}
              >
                {t.title}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div className={styles.ask}>
        {history.length > 0 && (
          <ol
            aria-label="Earlier in this conversation"
            className={styles.history}
          >
            {history.map((m, i) => (
              <li key={i} data-role={m.role}>
                <span className={styles.label}>
                  {m.role === "user" ? "You asked:" : "Answer:"}
                </span>
                <ReactMarkdown skipHtml>{m.content}</ReactMarkdown>
              </li>
            ))}
          </ol>
        )}
        <form onSubmit={onSubmit} className={styles.form}>
          <label htmlFor="question">Your question</label>
          <textarea
            id="question"
            name="question"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            aria-describedby="question-hint"
          />
          <p id="question-hint" className={styles.hint}>
            Press Enter to ask, Shift+Enter for a new line.
          </p>
          <button type="submit" disabled={running}>
            Ask
          </button>
        </form>

        {run.status !== "idle" && (
          <>
            <p className={styles.question}>
              <span className={styles.label}>You asked:</span> {run.question}
            </p>

            <ol aria-label="Trajectory" className={styles.trajectory}>
              {run.trajectory.map((step, i) => (
                <li key={i} data-finished={step.finished}>
                  {step.node}{" "}
                  <span aria-hidden="true">{step.finished ? "✓" : "…"}</span>{" "}
                  <span className={styles.visuallyHidden}>
                    {step.finished ? "finished" : "running"}
                  </span>
                </li>
              ))}
            </ol>

            {run.status === "failed" ? (
              <div role="alert" className={styles.alert}>
                <p>
                  <strong>
                    The answer is incomplete and must not be trusted.
                  </strong>{" "}
                  {run.reason}
                </p>
                <button type="button" onClick={() => void ask(run.question)}>
                  Retry
                </button>
              </div>
            ) : (
              <section
                aria-labelledby="answer-heading"
                className={styles.answer}
              >
                <h2 id="answer-heading">Answer</h2>
                <div aria-live="polite" aria-busy={running}>
                  <ReactMarkdown skipHtml>{run.answer}</ReactMarkdown>
                </div>
                {(run.citations.length > 0 || run.stances.length > 0) && (
                  <Sources citations={run.citations} stances={run.stances} />
                )}
                {run.drafts.map((draft) => (
                  <DraftPreview key={draft.draft_id} draft={draft} />
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Citation chips: the number used in the answer, the document and section; open one to read the quoted span. */
function Sources({
  citations,
  stances,
}: {
  citations: CitationEvent[];
  stances: PolicyStanceEvent[];
}) {
  return (
    <>
      <h3 id="sources-heading" className={styles.sourcesHeading}>
        Sources
      </h3>
      {stances.map((stance) => (
        <PolicyStanceCard key={stance.policy_id} stance={stance} />
      ))}
      <ol aria-labelledby="sources-heading" className={styles.sources}>
        {citations.map((c) => (
          <li key={c.index}>
            <details className={styles.chip}>
              <summary>
                <span className={styles.marker}>[{c.index}]</span> {c.title}{" "}
                <span className={styles.location}>{c.location}</span>
              </summary>
              <blockquote>{c.quote}</blockquote>
              <SourceViewer citation={c} />
            </details>
          </li>
        ))}
      </ol>
    </>
  );
}
