"use client";

import { useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import { parseRunEvents, type CitationEvent, type DraftEvent } from "@/lib/events";
import { DraftPreview } from "./DraftPreview";
import { SourceViewer } from "./SourceViewer";
import styles from "./ask.module.css";

type Step = { node: string; finished: boolean };

type Answer = {
  question: string;
  answer: string;
  citations: CitationEvent[];
  drafts: DraftEvent[];
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

export function AskScreen() {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<Run>({ status: "idle" });
  const threadId = useRef<string | null>(null);
  const running = run.status === "running";

  async function ask(text: string) {
    let trajectory: Step[] = [];
    let answer = "";
    let citations: CitationEvent[] = [];
    let drafts: DraftEvent[] = [];
    const update = (status: "running" | "done") =>
      setRun({ status, question: text, answer, citations, drafts, trajectory });
    update("running");
    try {
      threadId.current ??= await createThread();
      const response = await fetch(`/api/threads/${encodeURIComponent(threadId.current)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ message: text }),
      });
      if (response.status !== 200 || !response.body) throw new RunFailed(failureFor(response.status));

      for await (const event of parseRunEvents(response.body)) {
        switch (event.type) {
          case "node":
            trajectory =
              event.status === "started"
                ? [...trajectory, { node: event.node, finished: false }]
                : trajectory.map((step) =>
                    step.node === event.node && !step.finished ? { ...step, finished: true } : step,
                  );
            update("running");
            break;
          case "token":
            answer += event.text;
            update("running");
            break;
          case "citation":
            citations = [...citations, event];
            update("running");
            break;
          case "draft":
            drafts = [...drafts, event];
            update("running");
            break;
          case "error":
            throw new RunFailed(event.message);
          case "done":
            update("done");
            return;
        }
      }
      throw new RunFailed("The connection closed before the answer was complete.");
    } catch (error) {
      const reason =
        error instanceof RunFailed
          ? error.message
          : "The answer could not be received. Check your connection.";
      setRun({ status: "failed", question: text, reason, trajectory });
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || running) return;
    setQuestion("");
    void ask(text);
  }

  return (
    <div className={styles.ask}>
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
                {step.node} <span aria-hidden="true">{step.finished ? "✓" : "…"}</span>{" "}
                <span className={styles.visuallyHidden}>{step.finished ? "finished" : "running"}</span>
              </li>
            ))}
          </ol>

          {run.status === "failed" ? (
            <div role="alert" className={styles.alert}>
              <p>
                <strong>The answer is incomplete and must not be trusted.</strong> {run.reason}
              </p>
              <button type="button" onClick={() => void ask(run.question)}>
                Retry
              </button>
            </div>
          ) : (
            <section aria-labelledby="answer-heading" className={styles.answer}>
              <h2 id="answer-heading">Answer</h2>
              <div aria-live="polite" aria-busy={running}>
                <ReactMarkdown skipHtml>{run.answer}</ReactMarkdown>
              </div>
              {run.citations.length > 0 && <Sources citations={run.citations} />}
              {run.drafts.map((draft) => (
                <DraftPreview key={draft.draft_id} draft={draft} />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}

/** Citation chips: the number used in the answer, the document and section; open one to read the quoted span. */
function Sources({ citations }: { citations: CitationEvent[] }) {
  return (
    <>
      <h3 id="sources-heading" className={styles.sourcesHeading}>
        Sources
      </h3>
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
