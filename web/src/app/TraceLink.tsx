import styles from "./ask.module.css";

/**
 * Developers only: the LangSmith trace of the run that answered (nodes, branches, Claude and tool calls). The BFF
 * redirects to it, so plg-api decides who may see it and the browser never learns a LangSmith credential.
 */
export function TraceLink({ threadId, runId }: { threadId: string; runId: string }) {
  return (
    <a
      className={styles.traceLink}
      href={`/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/trace`}
      target="_blank"
      rel="noopener noreferrer"
    >
      View trace
    </a>
  );
}
