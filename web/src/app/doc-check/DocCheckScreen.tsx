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
import { Badge, Card, TableScroll, tableClass } from "../Card";
import { day } from "../dates";
import { DocCheckCard } from "../DocCheckCard";
import { DraftPreview } from "../DraftPreview";
import { ACTIVE_THREAD, createThread, failureFor, RunFailed, startRun } from "../runClient";
import { useShell } from "../shell/ShellContext";
import styles from "./doc-check.module.css";

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

/** What the picked application's row says while and after it is checked. */
const CHECK_STATUS_LABEL: Record<Check["status"], string> = { running: "Checking…", done: "Checked", failed: "Check failed" };

/** Applications with a submission bundle; pick one to check its documents in a new conversation. */
export function DocCheckScreen() {
  const [submissions, setSubmissions] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const running = check?.status === "running";
  const shell = useShell();

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
          case "cancelled": // stopped from the conversation, on the Ask screen
            throw new RunFailed("The check was stopped before it finished. Run it again.");
          case "done":
            acc.status = "done";
            update();
            shell.refresh(); // the sidebar lists the conversation and counts the proposed notice
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
        <h2 id="applications-heading" className={styles.step}>
          Applications
        </h2>
        <p className={styles.intro}>Pick an application to check its submitted documents against its checklist.</p>
        {error && (
          <Card role="alert" tone="danger">
            <p>{error}</p>
          </Card>
        )}
        {!submissions && !error && (
          <p role="status" className={styles.intro}>
            Loading…
          </p>
        )}
        {submissions && submissions.length === 0 && <p>No application has submitted documents.</p>}
        {submissions && submissions.length > 0 && (
          <div className={styles.frame}>
            <TableScroll label="Applications">
              <table aria-labelledby="applications-heading" className={tableClass}>
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
                  {submissions.map((s) => {
                    const picked = check?.applicationId === s.application_id;
                    return (
                      <tr
                        key={s.application_id}
                        className={picked ? styles.picked : undefined}
                        aria-current={picked || undefined}
                      >
                        <th scope="row" className={styles.appId}>
                          {s.application_id}
                        </th>
                        <td>{s.app_type_label}</td>
                        <td>{s.tenant_name}</td>
                        <td>{s.unit_id}</td>
                        <td>{day(s.submitted_date)}</td>
                        <td>
                          <Badge>{s.status}</Badge>
                        </td>
                        <td>{s.files}</td>
                        <td className={styles.pick}>
                          <button
                            type="button"
                            disabled={running}
                            aria-label={`Check ${s.application_id}`}
                            onClick={() => void run(s.application_id)}
                          >
                            Check
                          </button>
                          {picked && check && <span className={styles.pickedLabel}>{CHECK_STATUS_LABEL[check.status]}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TableScroll>
          </div>
        )}
      </section>

      {check && (
        <section aria-labelledby="result-heading" className={styles.result} aria-busy={running}>
          <h2 id="result-heading" className={styles.step}>
            Check of {check.applicationId}
          </h2>
          {check.status === "running" && (
            <p role="status" className={styles.intro}>
              Checking the submitted documents…
            </p>
          )}
          {check.status === "failed" ? (
            <Card role="alert" tone="danger">
              <p>
                <strong>The check is incomplete and must not be trusted.</strong> {check.reason}
              </p>
              <button type="button" onClick={() => void run(check.applicationId)}>
                Retry
              </button>
            </Card>
          ) : (
            <>
              <AnswerText markdown={check.answer} />
              {check.checks.map((found) => (
                <DocCheckCard key={found.seq} check={found} />
              ))}
              {check.drafts.map((draft) => (
                <DraftPreview key={draft.draft_id} draft={draft} />
              ))}
            </>
          )}
          {check.status !== "running" && check.threadId && (
            <p className={styles.next}>
              {check.status === "done" && check.proposed.length > 0 && (
                <Link href="/approvals" className={styles.primaryLink}>
                  Review the notice in Approvals
                </Link>
              )}
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
