"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  InvalidFrameError,
  parseRunEvents,
  type DocCheckEvent,
  type DraftEvent,
  type ProposedActionEvent,
  type Submission,
} from "@/lib/events";
import { AnswerText } from "../AnswerText";
import { day } from "../dates";
import { DocCheckCard } from "../DocCheckCard";
import { DraftPreview } from "../DraftPreview";
import { ACTIVE_THREAD, createThread, failureFor, RunFailed, startRun } from "../runClient";
import styles from "../ask.module.css";

/** The question the Document check screen asks for an application. */
export function checkQuestion(applicationId: string): string {
  return `Is application ${applicationId} complete? Check the submitted documents.`;
}

type Check = {
  applicationId: string;
  status: "running" | "done" | "failed";
  threadId: string | null;
  answer: string;
  checks: DocCheckEvent[];
  drafts: DraftEvent[];
  proposed: ProposedActionEvent[];
  reason: string;
};

/** Applications with a submission bundle; pick one to check its documents in a new conversation. */
export function DocCheckScreen() {
  const [submissions, setSubmissions] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const running = check?.status === "running";

  useEffect(() => {
    let current = true;
    fetch("/api/submissions")
      .then(async (response) => {
        if (!current) return;
        if (!response.ok) return setError("Could not load the applications.");
        const found = (await response.json()) as Submission[];
        if (current) setSubmissions(found);
      })
      .catch(() => current && setError("Could not load the applications."));
    return () => {
      current = false;
    };
  }, []);

  async function run(applicationId: string) {
    const acc: Check = {
      applicationId, status: "running", threadId: null, answer: "", checks: [], drafts: [], proposed: [], reason: "",
    };
    const update = () => setCheck({ ...acc });
    update();
    try {
      acc.threadId = await createThread();
      update();
      const response = await startRun(acc.threadId, checkQuestion(applicationId));
      if (response.status !== 200 || !response.body) throw new RunFailed(failureFor(response.status));
      for await (const event of parseRunEvents(response.body)) {
        switch (event.type) {
          case "token":
            acc.answer += event.text;
            break;
          case "doc_check":
            acc.checks = [...acc.checks, event];
            break;
          case "draft":
            acc.drafts = [...acc.drafts, event];
            break;
          case "proposed_action":
            acc.proposed = [...acc.proposed, event];
            break;
          case "error":
            throw new RunFailed(event.message);
          case "done":
            acc.status = "done";
            update();
            return;
        }
        update();
      }
      throw new RunFailed("The connection closed before the check was complete.");
    } catch (error) {
      acc.status = "failed";
      acc.reason =
        error instanceof RunFailed
          ? error.message
          : error instanceof InvalidFrameError
            ? "The check could not be read."
            : "The check could not be received. Check your connection.";
      update();
    }
  }

  return (
    <>
      <section aria-labelledby="applications-heading">
        <h2 id="applications-heading">Applications</h2>
        {error && <p role="alert">{error}</p>}
        {!submissions && !error && <p>Loading…</p>}
        {submissions && submissions.length === 0 && <p>No application has submitted documents.</p>}
        {submissions && submissions.length > 0 && (
          <table aria-labelledby="applications-heading" className={styles.checklist}>
            <thead>
              <tr>
                <th scope="col">Application</th>
                <th scope="col">Type</th>
                <th scope="col">Tenant</th>
                <th scope="col">Unit</th>
                <th scope="col">Submitted</th>
                <th scope="col">Status</th>
                <th scope="col">Files</th>
                <th scope="col">
                  <span className={styles.visuallyHidden}>Check</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {submissions.map((s) => (
                <tr key={s.application_id}>
                  <th scope="row">{s.application_id}</th>
                  <td>{s.app_type_label}</td>
                  <td>{s.tenant_name}</td>
                  <td>{s.unit_id}</td>
                  <td>{day(s.submitted_date)}</td>
                  <td>{s.status}</td>
                  <td>{s.files}</td>
                  <td>
                    <button
                      type="button"
                      disabled={running}
                      aria-label={`Check ${s.application_id}`}
                      onClick={() => void run(s.application_id)}
                    >
                      Check
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {check && (
        <section aria-labelledby="result-heading" className={styles.answer} aria-busy={running}>
          <h2 id="result-heading">Check of {check.applicationId}</h2>
          {check.status === "running" && <p role="status">Checking the submitted documents…</p>}
          {check.status === "failed" ? (
            <div role="alert" className={styles.alert}>
              <p>
                <strong>The check is incomplete and must not be trusted.</strong> {check.reason}
              </p>
              <button type="button" onClick={() => void run(check.applicationId)}>
                Retry
              </button>
            </div>
          ) : (
            <>
              <AnswerText markdown={check.answer} />
              {check.checks.map((found) => (
                <DocCheckCard key={found.seq} check={found} />
              ))}
              {check.drafts.map((draft) => (
                <DraftPreview key={draft.draft_id} draft={draft} />
              ))}
              {check.status === "done" && check.proposed.length > 0 && (
                <p>
                  <Link href="/approvals">Review the notice in Approvals</Link>
                </p>
              )}
            </>
          )}
          {check.status !== "running" && check.threadId && (
            <p>
              <Link
                href="/"
                onClick={() => {
                  if (check.threadId) sessionStorage.setItem(ACTIVE_THREAD, check.threadId);
                }}
              >
                Open the conversation
              </Link>
            </p>
          )}
        </section>
      )}
    </>
  );
}
