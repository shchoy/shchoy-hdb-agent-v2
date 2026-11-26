/** Browser-side uploads into the officer's private library (#103), through the BFF's /api/uploads. */
import type { Upload } from "@/lib/events";

/** What the file picker offers; plg-api decides what it accepts (and says why it refuses). */
export const ACCEPT = ".pdf,.docx,.txt,.md,.eml,.png,.jpg,.jpeg";

/** At most this many files go with one question (plg-api enforces it too). */
export const MAX_ATTACHMENTS = 5;

/** A size for people: "220 B", "1.5 KB", "3.2 MB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size < 10 ? size.toFixed(1).replace(/\.0$/, "") : Math.round(size)} ${units[unit]}`;
}

export type UploadOutcome = { ok: true; upload: Upload } | { ok: false; detail: string } | { ok: false; aborted: true };

/** The reason the officer sees for a refusal: plg-api's detail when it gave one. */
function refusal(status: number, body: string): string {
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
  } catch {
    // not JSON: fall through
  }
  if (status === 401) return "You are no longer signed in. Sign in again, then retry.";
  return status ? `The file could not be uploaded (HTTP ${status}).` : "The file could not be uploaded. Check your connection.";
}

/**
 * Uploads one file with XMLHttpRequest, so the bytes sent can be reported (`onProgress(loaded, total)`; fetch can't).
 * `abort()` stops it; the outcome then says `aborted`.
 */
export function uploadFile(
  file: File,
  onProgress: (loaded: number, total: number) => void,
): { done: Promise<UploadOutcome>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const done = new Promise<UploadOutcome>((resolve) => {
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      if (xhr.status === 201 || xhr.status === 200) {
        try {
          resolve({ ok: true, upload: JSON.parse(xhr.responseText) as Upload });
        } catch {
          resolve({ ok: false, detail: refusal(xhr.status, "") });
        }
      } else {
        resolve({ ok: false, detail: refusal(xhr.status, xhr.responseText) });
      }
    };
    xhr.onerror = () => resolve({ ok: false, detail: refusal(0, "") });
    xhr.onabort = () => resolve({ ok: false, aborted: true });
  });
  xhr.open("POST", `/api/uploads?${new URLSearchParams({ filename: file.name })}`);
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.send(file);
  return { done, abort: () => xhr.abort() };
}
