"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import {
  InvalidFrameError,
  parseRunEvents,
  type CitationEvent,
  type ClassificationEvent,
  type DocCheckEvent,
  type DraftEvent,
  type InjectionEvent,
  type PolicyStanceEvent,
  type ProposedActionEvent,
  type SqlTraceEvent,
  type TasksEvent,
  type ThreadView,
  type UserCtx,
} from "@/lib/events";
import { AnswerActions } from "./AnswerActions";
import { AnswerText, type OnCite } from "./AnswerText";
import { ApprovalCard } from "./ApprovalCard";
import { AttachmentChips, PaperclipIcon, useAttachments, type Attached } from "./Attachments";
import type { Approvable } from "./approvals/ActionCard";
import { ClassificationCard } from "./ClassificationCard";
import { DocCheckCard } from "./DocCheckCard";
import { DraftPreview } from "./DraftPreview";
import { InjectionAlert } from "./InjectionAlert";
import { ReasoningPanel } from "./ReasoningPanel";
import { NO_SOURCES, SourcesPanel, type AnswerSources } from "./SourcesPanel";
import { TaskList } from "./TaskList";
import { Welcome } from "./Welcome";
import styles from "./ask.module.css";
import { ACTIVE_THREAD, createThread, failureFor, RunFailed, startRun } from "./runClient";
import { ACCEPT } from "./uploads";
import { useConversationControl, useShell } from "./shell/ShellContext";

type Step = { node: string; finished: boolean };

type Answer = {
  question: string;
  /** The files sent with the question (#103), shown with its bubble. */
  attached: Attached[];
  answer: string;
  citations: CitationEvent[];
  classifications: ClassificationEvent[];
  docChecks: DocCheckEvent[];
  drafts: DraftEvent[];
  injections: InjectionEvent[];
  stances: PolicyStanceEvent[];
  tasks: TasksEvent[];
  traces: SqlTraceEvent[];
  /** The actions waiting for approval when the run ended (the thread's, re-sent by every run that pauses on them). */
  actions: ProposedActionEvent[];
  trajectory: Step[];
  /** The run that answered, from its `done` event: what feedback on the answer names. */
  runId?: string;
};

type Run =
  | { status: "idle" }
  | ({ status: "running" } & Answer)
  | ({ status: "done" } & Answer)
  | { status: "failed"; question: string; attached: Attached[]; reason: string; trajectory: Step[] }
  /** The officer pressed Stop: plg-api cancelled the run, so nothing of the turn was kept. */
  | { status: "stopped"; question: string; attached: Attached[]; trajectory: Step[] };

/** What an answer's markers open. */
function sourcesOfRun(answer: Answer): AnswerSources {
  return { citations: answer.citations, stances: answer.stances };
}

function emptyAnswer(question: string, attached: Attached[] = []): Answer {
  return { question, attached, answer: "", citations: [], classifications: [], docChecks: [], drafts: [], injections: [], stances: [], tasks: [], traces: [], actions: [], trajectory: [] };
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

/** The sources panel: whose sources, the source it opened at, and the marker (or button) that opened it. */
type Panel = { sources: AnswerSources; index: number; openCount: number; opener: HTMLButtonElement };

/** A proposed action in its thread: from a `proposed_action` event (its type and seq ride along) or ThreadView.pending. */
function approvable(threadId: string, action: Omit<Approvable, "thread_id" | "thread_title">): Approvable {
  return { ...action, thread_id: threadId };
}

/** The run's stream stopped before `done`; it may be picked up again from the last event seen. */
class Interrupted extends Error {}

/**
 * `developer`: the signed-in persona is a developer, who gets "View trace" in each answer's action bar.
 * `user`: the signed-in persona, greeted with starter prompts for their role in a new conversation.
 */
export function AskScreen({
  developer = false,
  user,
}: {
  developer?: boolean;
  user?: Pick<UserCtx, "name" | "role" | "staff_id">;
}) {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<Run>({ status: "idle" });
  const [history, setHistory] = useState<ThreadView["messages"]>([]);
  /** The run that answered each earlier answer, by its index in `history`. */
  const [answeredBy, setAnsweredBy] = useState<Record<number, string>>({});
  /** The sources of each earlier answer, by its index in `history`: what its `[n]` markers open. */
  const [sourcesOf, setSourcesOf] = useState<Record<number, AnswerSources>>({});
  /** The actions a reopened conversation is paused on: shown in its last answer. */
  const [pending, setPending] = useState<Approvable[]>([]);
  const [panel, setPanel] = useState<Panel | null>(null);
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
  const picker = useRef<HTMLInputElement>(null);
  const attachments = useAttachments();

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

  /** Opens the sources panel on one answer's sources, at source `index`. */
  const cite =
    (sources: AnswerSources): OnCite =>
    (index, opener) =>
      setPanel((open) => ({ sources, index, opener, openCount: (open?.openCount ?? 0) + 1 }));

  /** Closes the sources panel; focus goes back to the marker that opened it (else to the composer). */
  function closePanel() {
    const opener = panel?.opener;
    setPanel(null);
    if (opener?.isConnected) opener.focus();
    else composer.current?.focus();
  }

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
              case "proposed_action":
                // One card per action: a revised version replaces the one before it.
                acc.actions = [...acc.actions.filter((a) => a.action_id !== event.action_id), event];
                break;
              case "error":
                throw new RunFailed(event.message);
              case "cancelled":
                setRun({ status: "stopped", question: acc.question, attached: acc.attached, trajectory: acc.trajectory });
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
        attached: acc.attached,
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

  /** Asks `text` with the officer's uploads in `attached` (#103). */
  async function ask(text: string, attached: Attached[] = []) {
    if (run.status === "done") {
      const { runId } = run;
      if (runId) setAnsweredBy((by) => ({ ...by, [history.length + 1]: runId }));
      setSourcesOf((of) => ({ ...of, [history.length + 1]: sourcesOfRun(run) }));
      setHistory((h) => [
        ...h,
        { role: "user", content: run.question },
        { role: "assistant", content: run.answer },
      ]);
    }
    setRun({ status: "running", ...emptyAnswer(text, attached) });
    setPending([]); // the new run lists whatever is still pending when it ends
    setPanel(null);
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
      setRun({ status: "failed", question: text, attached, reason, trajectory: [] });
      return;
    }
    const id = threadId.current;
    const uploads = attached.map((a) => a.upload_id);
    await follow(text, () => startRun(id, text, uploads), emptyAnswer(text, attached));
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
    if (id !== threadId.current) setPanel(null); // re-reading the same conversation keeps its open panel
    threadId.current = id;
    setActive(id);
    sessionStorage.setItem(ACTIVE_THREAD, id);
    setHistory(thread.messages);
    setPending((thread.pending ?? []).map((action) => approvable(id, action)));
    setAnsweredBy(Object.fromEntries((thread.turns ?? []).map((t) => [t.message_index, t.run_id])));
    setSourcesOf(
      Object.fromEntries(
        (thread.turns ?? []).map((t) => [t.message_index, { citations: t.citations ?? [], stances: t.stances ?? [] }]),
      ),
    );
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
    setSourcesOf({});
    setPending([]);
    setPanel(null);
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
    if (!text || running || attachments.uploading) return;
    setQuestion("");
    const attached = attachments.ready;
    attachments.clear();
    void ask(text, attached);
  }

  /** Files dragged over the conversation (never the sidebar's conversations and groups: they carry no Files). */
  const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
  const dragDepth = useRef(0);
  const [dropping, setDropping] = useState(false);
  const onDragEnter = (event: DragEvent) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    dragDepth.current += 1;
    setDropping(true);
  };
  const onDragOver = (event: DragEvent) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };
  const onDragLeave = (event: DragEvent) => {
    if (!carriesFiles(event)) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDropping(false);
  };
  const onDrop = (event: DragEvent) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDropping(false);
    attachments.add(Array.from(event.dataTransfer.files));
    composer.current?.focus();
  };

  return (
    <div
      className={styles.ask}
      data-panel={panel ? "" : undefined}
      data-dropping={dropping ? "" : undefined}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <section aria-label="Conversation" className={styles.thread}>
        {showWelcome && user && (
          <Welcome user={user} onAsk={(text) => void ask(text)} />
        )}
        {history.length > 0 && (
          <ol aria-label="Earlier in this conversation" className={styles.history}>
            {history.map((m, i) => {
              const sources = sourcesOf[i] ?? NO_SOURCES;
              return (
              <li key={i} data-role={m.role}>
                {m.role === "user" ? (
                  <Bubble text={m.content} />
                ) : (
                  <div className={styles.reply}>
                    <span className={styles.visuallyHidden}>Answer:</span>
                    <AnswerText markdown={m.content} citations={sources.citations} onCite={cite(sources)} />
                    <SourcesButton sources={sources} onCite={cite(sources)} />
                    {i === history.length - 1 && run.status === "idle" && (
                      <PendingActions actions={pending} user={user} onDecided={shell.refresh} />
                    )}
                    {answeredBy[i] && active && (
                      <AnswerActions
                        threadId={active}
                        runId={answeredBy[i]}
                        markdown={m.content}
                        citations={sources.citations}
                        developer={developer}
                      />
                    )}
                  </div>
                )}
              </li>
              );
            })}
          </ol>
        )}

        {run.status !== "idle" && (
          <div className={styles.turn}>
            <Bubble text={run.question} attached={run.attached} />

            {run.status === "failed" ? (
              <div role="alert" className={styles.alert}>
                <p>
                  <strong>The answer is incomplete and must not be trusted.</strong> {run.reason}
                </p>
                <button type="button" onClick={() => void ask(run.question, run.attached)}>
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
                  <AnswerText markdown={run.answer} citations={run.citations} onCite={cite(sourcesOfRun(run))} />
                </div>
                <SourcesButton sources={sourcesOfRun(run)} onCite={cite(sourcesOfRun(run))} />
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
                {run.status === "done" && active && (
                  <PendingActions actions={run.actions.map((a) => approvable(active, a))} user={user} onDecided={shell.refresh} />
                )}
                {run.status === "done" && run.runId && active && (
                  <AnswerActions
                    key={run.runId}
                    threadId={active}
                    runId={run.runId}
                    markdown={run.answer}
                    citations={run.citations}
                    developer={developer}
                  />
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
        {dropping && (
          <p className={styles.dropHint} aria-hidden="true">
            Drop files to attach them to your question
          </p>
        )}
        <AttachmentChips
          chips={attachments.chips}
          notice={attachments.notice}
          announcement={attachments.announcement}
          onRemove={(key) => {
            attachments.remove(key);
            composer.current?.focus();
          }}
        />
        <label htmlFor="question" className={styles.visuallyHidden}>
          Your question
        </label>
        <div className={styles.composerRow}>
          <button
            type="button"
            className={styles.attach}
            aria-label="Attach files"
            title="Attach files (PDF, Word, text, Markdown or email)"
            onClick={() => picker.current?.click()}
          >
            <PaperclipIcon />
          </button>
          <input
            ref={picker}
            type="file"
            multiple
            accept={ACCEPT}
            hidden
            tabIndex={-1}
            onChange={(event) => {
              attachments.add(Array.from(event.currentTarget.files ?? []));
              event.currentTarget.value = ""; // the same file can be picked again
            }}
          />
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
            <button type="submit" disabled={attachments.uploading}>
              Ask
            </button>
          )}
        </div>
        <p id="question-hint" className={styles.hint}>
          {attachments.uploading
            ? "Wait for your files to finish uploading, then ask."
            : "Press Enter to ask, Shift+Enter for a new line. Attach up to 5 files, or drop them here."}
        </p>
      </form>
      <div ref={end} className={styles.end} />
      {panel && (
        <SourcesPanel sources={panel.sources} index={panel.index} openCount={panel.openCount} onClose={closePanel} />
      )}
    </div>
  );
}

/** The actions an answer left waiting for approval, one card each; decided in place by the signed-in persona. */
function PendingActions({
  actions,
  user,
  onDecided,
}: {
  actions: Approvable[];
  user?: Pick<UserCtx, "role" | "staff_id">;
  onDecided: () => void;
}) {
  if (!user || actions.length === 0) return null;
  return actions.map((action) => (
    <ApprovalCard key={`${action.action_id}-v${action.version}`} action={action} user={user} onDecided={onDecided} />
  ));
}

/** The officer's question: a right-aligned bubble, with the files sent with it (#103) listed below the text. */
function Bubble({ text, attached = [] }: { text: string; attached?: Attached[] }) {
  return (
    <div className={styles.bubble}>
      <p data-bubble className={styles.bubbleText}>
        <span className={styles.visuallyHidden}>You asked: </span>
        {text}
      </p>
      {attached.length > 0 && (
        <ul aria-label="Files sent with your question" className={styles.bubbleFiles}>
          {attached.map((file) => (
            <li key={file.upload_id}>
              <PaperclipIcon />
              {file.filename}
            </li>
          ))}
        </ul>
      )}
    </div>
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

/** Opens the sources panel at the answer's first source; none when the answer has no sources. */
function SourcesButton({ sources, onCite }: { sources: AnswerSources; onCite: OnCite }) {
  const count = sources.citations.length;
  if (count === 0 && sources.stances.length === 0) return null;
  const first = sources.citations[0]?.index ?? 0;
  return (
    <button type="button" className={styles.sourcesButton} onClick={(event) => onCite(first, event.currentTarget)}>
      Sources ({count})
    </button>
  );
}
