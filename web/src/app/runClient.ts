/** Browser-side helpers shared by the screens that start runs through the BFF. */

/** The run failed or was cut short: whatever was streamed is partial and not to be trusted. */
export class RunFailed extends Error {}

/** What to tell the officer when the BFF answers with an error status. */
export function failureFor(status: number): string {
  return status === 401
    ? "You are no longer signed in. Sign in again, then retry."
    : `The service responded with an error (HTTP ${status}).`;
}

/** Creates a conversation for the signed-in officer; returns its thread ID. */
export async function createThread(): Promise<string> {
  const response = await fetch("/api/threads", { method: "POST" });
  if (!response.ok) throw new RunFailed(failureFor(response.status));
  const { thread_id } = (await response.json()) as { thread_id: string };
  return thread_id;
}

/** Starts a run of `message` on the thread; the response is the SSE stream (or the BFF's refusal). */
export function startRun(threadId: string, message: string): Promise<Response> {
  return fetch(`/api/threads/${encodeURIComponent(threadId)}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message }),
  });
}

/** The conversation the Ask screen reopens on load (sessionStorage key), so another screen can hand one over. */
export const ACTIVE_THREAD = "plg_active_thread";
