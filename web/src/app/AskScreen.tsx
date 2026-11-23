"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import {
  InvalidFrameError,
  parseRunEvents,
  type CitationEvent,
  type ClassificationEvent,
  type DocCheckEvent,
  type DraftEvent,
  type InjectionEvent,
  type PolicyStanceEvent,
  type SqlTraceEvent,
  type TasksEvent,
  type ThreadView,
  type UserCtx,
} from "@/lib/events";
import { AnswerFeedback } from "./AnswerFeedback";
import { AnswerText } from "./AnswerText";
import { TraceLink } from "./TraceLink";
import { ClassificationCard } from "./ClassificationCard";
import { DocCheckCard } from "./DocCheckCard";
import { DraftPreview } from "./DraftPreview";
import { InjectionAlert } from "./InjectionAlert";
import { PolicyStanceCard } from "./PolicyStanceCard";
import { ReasoningPanel } from "./ReasoningPanel";
import { SourceViewer } from "./SourceViewer";
import { TaskList } from "./TaskList";
import { Welcome } from "./Welcome";
import styles from "./ask.module.css";
import { ACTIVE_THREAD, createThread, failureFor, RunFailed, startRun } from "./runClient";
import { useConversationControl, useShell } from "./shell/ShellContext";

type Step = { node: string; finished: boolean };

type Answer = {
  question: string;
  answer: string;
  citations: CitationEvent[];
  classifications: ClassificationEvent[];
  docChecks: DocCheckEvent[];
  drafts: DraftEvent[];
  injections: InjectionEvent[];
  stances: PolicyStanceEvent[];
  tasks: TasksEvent[];
  traces: SqlTraceEvent[];
  trajectory: Step[];
  /** The run that answered, from its `done` event: what feedback on the answer names. */
  runId?: string;
};

type Run =
  | { status: "idle" }
  | ({ status: "running" } & Answer)
  | ({ status: "done" } & Answer)
  | { status: "failed"; question: string; reason: string; trajectory: Step[] }
  /** The officer pressed Stop: plg-api cancelled the run, so nothing of the turn was kept. */
  | { status: "stopped"; question: string; trajectory: Step[] };

function emptyAnswer(question: string): Answer {
  return { question, answer: "", citations: [], classifications: [], docChecks: [], drafts: [], injections: [], stances: [], tasks: [], traces: [], trajectory: [] };
}

const RESUME_ATTEMPTS = 3;

/**
 * What each graph node is doing, in plain words, for the status line while an answer is written. The names are
 * the graph's nodes (src/plg/graph/build.py); a node missing here shows "Working…".
 */
const DOING: Record<string, string> = {
  screen_input: "Checking your message…",
  summarise_history: "Reading the conversation so far…",
  load_memory: "Recalling your notes…",
  route: "Working out what you need…",
  knowledge: "Searching the library…",
  data: "Querying PLG Records…",
  drafting: "Drafting the letter…",
  defect: "Classifying the feedback…",
  doc_check: "Checking the documents…",
  tasks: "Ranking the tasks…",
  glossary: "Reading the glossary…",
  category_summary: "Summarising the category…",
  merge: "Writing the answer…",
  write_memory: "Saving notes…",
  approval: "Waiting for approval…",
  execute_action: "Carrying out the decision…",
};

/** The status line: the latest step still running (specialists run in parallel), else a generic one. */
function statusLine(trajectory: Step[]): string {
  const step = trajectory.findLast((s) => !s.finished);
  return (step && DOING[step.node]) ?? "Working…";
}

/** Within this many pixels of the bottom counts as "at the latest": the view keeps following the answer. */
const FOLLOW_SLACK = 48;

/** Keys that scroll the window up. */
const SCROLL_UP_KEYS = new Set(["ArrowUp", "PageUp", "Home"]);

function atBottom(): boolean {
  const page = document.documentElement;
  return window.innerHeight + window.scrollY >= page.scrollHeight - FOLLOW_SLACK;
}

/** The run's stream stopped before `done`; it may be picked up again from the last event seen. */
class Interrupted extends Error {}

/**
 * `developer`: the signed-in persona is a developer, who gets a "View trace" link on each answer.
 * `user`: the signed-in persona, greeted with starter prompts for their role in a new conversation.
 */
export function AskScreen({
  developer = false,
  user,
}: {
  developer?: boolean;
  user?: Pick<UserCtx, "name" | "role">;
}) {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<Run>({ status: "idle" });
  const [history, setHistory] = useState<ThreadView["messages"]>([]);
  /** The run that answered each earlier answer, by its index in `history`. */
  const [answeredBy, setAnsweredBy] = useState<Record<number, string>>({});
  const shell = useShell();
  const threadId = useRef<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const running = run.status === "running";
  /** Whether a conversation saved from before a refresh has been looked for, so the welcome never flashes over it. */
  const [restoreChecked, setRestoreChecked] = useState(false);
  /** Whether the view follows the conversation's end; it stops once the officer scrolls up. */
  const following = useRef(true);
  const [scrolledUp, setScrolledUp] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  /** Keeps the ref (read while rendering tokens) and the Jump to latest control in step. */
  const setFollowing = useCallback((follow: boolean) => {
    following.current = follow;
    setScrolledUp(!follow);
  }, []);

  const jumpToLatest = useCallback(() => {
    setFollowing(true);
    end.current?.scrollIntoView?.({ block: "end" });
  }, [setFollowing]);

  useEffect(() => {
    const onScroll = () => setFollowing(atBottom());
    /**
     * Scrolling up (wheel, touch drag, keys) stops following at once, before a token can pull the view back down;
     * the scroll that follows resumes it if the officer is still at the bottom. A page too short to scroll never stops.
     */
    const stop = () => {
      if (document.documentElement.scrollHeight > window.innerHeight) setFollowing(false);
    };
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) stop();
    };
    const onKey = (event: KeyboardEvent) => {
      if (SCROLL_UP_KEYS.has(event.key) && !(event.target instanceof HTMLTextAreaElement)) stop();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("touchmove", stop, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchmove", stop);
      window.removeEventListener("keydown", onKey);
    };
  }, [setFollowing]);

  // Keeps the newest of the conversation in view while following it.
  useEffect(() => {
    if (following.current) end.current?.scrollIntoView?.({ block: "end" });
  }, [run, history]);

  // The composer grows with its content; CSS caps it (max-height), past which it scrolls.
  useLayoutEffect(() => {
    const box = composer.current;
    if (!box) return;
    box.style.height = "auto";
    if (box.scrollHeight > 0) box.style.height = `${box.scrollHeight}px`;
  }, [question]);

  /** Reads one run to its end, from whatever stream `open` gives. Resumes after a dropped connection. */
  async function follow(
    text: string,
    open: (lastSeq: number) => Promise<Response>,
    prior?: Answer,
  ) {
    const acc: Answer = prior ?? emptyAnswer(text);
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
              case "classification":
                acc.classifications = [...acc.classifications, event];
                break;
              case "doc_check":
                acc.docChecks = [...acc.docChecks, event];
                break;
              case "tasks":
                acc.tasks = [...acc.tasks, event];
                break;
              case "injection":
                acc.injections = [...acc.injections, event];
                break;
              case "draft":
                acc.drafts = [...acc.drafts, event];
                break;
              case "policy_stance":
                acc.stances = [...acc.stances, event];
                break;
              case "sql_trace":
                acc.traces = [...acc.traces, event];
                break;
              case "error":
                throw new RunFailed(event.message);
              case "cancelled":
                setRun({ status: "stopped", question: acc.question, trajectory: acc.trajectory });
                composer.current?.focus(); // the Stop button is gone: the officer can ask again at once
                shell.refresh(); // a new conversation is listed, titled by the stopped question
                return;
              case "done":
                acc.runId = event.run_id;
                update("done");
                // The sidebar lists the conversation (new, or newly titled) and counts any action it proposed.
                shell.refresh();
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

  /** Stop generating: plg-api cancels the run, whose stream then ends with `cancelled`. */
  async function stop() {
    const id = threadId.current;
    if (!id) return;
    try {
      await fetch(`/api/threads/${encodeURIComponent(id)}/runs/latest/cancel`, { method: "POST" });
    } catch {
      // The run goes on (or has just ended): its stream still says how it finished.
    }
  }

  async function ask(text: string) {
    if (run.status === "done") {
      const { runId } = run;
      if (runId) setAnsweredBy((by) => ({ ...by, [history.length + 1]: runId }));
      setHistory((h) => [
        ...h,
        { role: "user", content: run.question },
        { role: "assistant", content: run.answer },
      ]);
    }
    setRun({ status: "running", ...emptyAnswer(text) });
    jumpToLatest();
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
    await follow(text, () => startRun(id, text));
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
    setAnsweredBy(Object.fromEntries((thread.turns ?? []).map((t) => [t.message_index, t.run_id])));
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
    setAnsweredBy({});
    setRun({ status: "idle" });
  }

  // The sidebar's conversation list and New conversation act on this screen while it is shown.
  useConversationControl({ open: (id) => void open(id), startNew }, active, running);

  useEffect(() => {
    const active = sessionStorage.getItem(ACTIVE_THREAD);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (active) void open(active).finally(() => setRestoreChecked(true));
    else setRestoreChecked(true);
    // Runs once on load: a refresh returns to the conversation (and answer) it interrupted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** A new conversation, nothing asked yet: the welcome and its starter prompts. */
  const showWelcome = user !== undefined && restoreChecked && history.length === 0 && run.status === "idle";

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || running) return;
    setQuestion("");
    void ask(text);
  }

  return (
    <div className={styles.ask}>
      <section aria-label="Conversation" className={styles.thread}>
        {showWelcome && user && (
          <Welcome user={user} onAsk={(text) => void ask(text)} />
        )}
        {history.length > 0 && (
          <ol aria-label="Earlier in this conversation" className={styles.history}>
            {history.map((m, i) => (
              <li key={i} data-role={m.role}>
                {m.role === "user" ? (
                  <Bubble text={m.content} />
                ) : (
                  <div className={styles.reply}>
                    <span className={styles.visuallyHidden}>Answer:</span>
                    <AnswerText markdown={m.content} />
                    {answeredBy[i] && active && (
                      <>
                        <AnswerFeedback threadId={active} runId={answeredBy[i]} />
                        {developer && <TraceLink threadId={active} runId={answeredBy[i]} />}
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}

        {run.status !== "idle" && (
          <div className={styles.turn}>
            <Bubble text={run.question} />

            {run.status === "failed" ? (
              <div role="alert" className={styles.alert}>
                <p>
                  <strong>The answer is incomplete and must not be trusted.</strong> {run.reason}
                </p>
                <button type="button" onClick={() => void ask(run.question)}>
                  Retry
                </button>
              </div>
            ) : run.status === "stopped" ? (
              <p className={styles.stopped}>
                <strong>Stopped.</strong> You stopped this answer, so nothing from it was kept. Ask again when you are ready.
              </p>
            ) : (
              <section aria-labelledby="answer-heading" className={styles.answer}>
                <h2 id="answer-heading" className={styles.visuallyHidden}>
                  Answer
                </h2>
                <InjectionAlert flags={run.injections} />
                <div aria-live="polite" aria-busy={running}>
                  <AnswerText markdown={run.answer} />
                </div>
                {(run.citations.length > 0 || run.stances.length > 0) && (
                  <Sources citations={run.citations} stances={run.stances} />
                )}
                {run.classifications.map((found) => (
                  <ClassificationCard key={found.seq} found={found} />
                ))}
                {run.docChecks.map((check) => (
                  <DocCheckCard key={check.seq} check={check} />
                ))}
                {run.tasks.map((digest) => (
                  <TaskList key={digest.seq} digest={digest} />
                ))}
                {run.drafts.map((draft) => (
                  <DraftPreview key={draft.draft_id} draft={draft} />
                ))}
                {run.status === "done" && run.runId && active && (
                  <>
                    <AnswerFeedback key={run.runId} threadId={active} runId={run.runId} />
                    {developer && <TraceLink threadId={active} runId={run.runId} />}
                  </>
                )}
              </section>
            )}

            {!running && (
              <details className={styles.steps}>
                <summary>Show steps</summary>
                <Trajectory steps={run.trajectory} />
                {run.status === "done" && run.traces.length > 0 && <ReasoningPanel traces={run.traces} />}
              </details>
            )}
          </div>
        )}

        {/* Always present, so screen readers announce each change; empty once the answer is done. */}
        <p role="status" aria-live="polite" className={styles.status}>
          {running ? statusLine(run.trajectory) : run.status === "stopped" ? "Answer stopped." : ""}
        </p>
      </section>

      <form onSubmit={onSubmit} className={styles.composer}>
        {scrolledUp && (
          <button type="button" className={styles.jump} onClick={jumpToLatest}>
            Jump to latest
          </button>
        )}
        <label htmlFor="question" className={styles.visuallyHidden}>
          Your question
        </label>
        <div className={styles.composerRow}>
          <textarea
            ref={composer}
            id="question"
            name="question"
            rows={1}
            placeholder="Ask a question…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            aria-describedby="question-hint"
          />
          {running ? (
            <button type="button" onClick={() => void stop()} disabled={!active}>
              Stop
            </button>
          ) : (
            <button type="submit">Ask</button>
          )}
        </div>
        <p id="question-hint" className={styles.hint}>
          Press Enter to ask, Shift+Enter for a new line.
        </p>
      </form>
      <div ref={end} />
    </div>
  );
}

/** The officer's question: a right-aligned bubble. */
function Bubble({ text }: { text: string }) {
  return (
    <p data-bubble className={styles.bubble}>
      <span className={styles.visuallyHidden}>You asked: </span>
      {text}
    </p>
  );
}

/** The graph nodes the run went through, each finished or still running. */
function Trajectory({ steps }: { steps: Step[] }) {
  return (
    <ol aria-label="Trajectory" className={styles.trajectory}>
      {steps.map((step, i) => (
        <li key={i} data-finished={step.finished}>
          {step.node} <span aria-hidden="true">{step.finished ? "✓" : "…"}</span>{" "}
          <span className={styles.visuallyHidden}>{step.finished ? "finished" : "running"}</span>
        </li>
      ))}
    </ol>
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
