"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Upload } from "@/lib/events";
import { Badge } from "./Card";
import { InjectionAlert } from "./InjectionAlert";
import styles from "./ask.module.css";
import { formatSize, MAX_ATTACHMENTS, uploadFile } from "./uploads";

/** One file attached to the question being written: uploading, ready (in the officer's library) or refused. */
export type Chip = {
  key: string;
  name: string;
  size: number;
  status: "uploading" | "ready" | "failed";
  /** Bytes sent so far; null until the first progress report (the bar is indeterminate until then). */
  loaded: number | null;
  upload?: Upload;
  /** Why it was refused (plg-api's detail). */
  detail?: string;
};

/** A file sent with a question: shown with the question bubble. */
export type Attached = Pick<Upload, "upload_id" | "filename">;

let nextKey = 0;

/**
 * The composer's attachments (#103): each added file is uploaded at once (XMLHttpRequest, so progress is real); at most
 * MAX_ATTACHMENTS per question (the rest are refused with a `notice`). `remove` aborts an upload still in flight.
 */
export function useAttachments() {
  const [chips, setChips] = useState<Chip[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  /** What a screen reader hears as uploads finish. */
  const [announcement, setAnnouncement] = useState("");
  const count = useRef(0);
  const aborts = useRef(new Map<string, () => void>());

  const patch = useCallback((key: string, change: Partial<Chip>) => {
    setChips((all) =>
      all.map((chip) => (chip.key === key ? { ...chip, ...change } : chip)),
    );
  }, []);

  const add = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const room = Math.max(0, MAX_ATTACHMENTS - count.current);
      const taken = files.slice(0, room);
      const left = files.slice(room);
      setNotice(
        left.length
          ? `You can attach up to ${MAX_ATTACHMENTS} files to one question. Not attached: ${left.map((f) => f.name).join(", ")}.`
          : null,
      );
      if (taken.length === 0) return;
      const added: Chip[] = taken.map((file) => ({
        key: `file-${++nextKey}`,
        name: file.name,
        size: file.size,
        status: "uploading",
        loaded: null,
      }));
      count.current += added.length;
      setChips((all) => [...all, ...added]);
      taken.forEach((file, i) => {
        const { key, name } = added[i];
        const { done, abort } = uploadFile(file, (loaded) =>
          patch(key, { loaded }),
        );
        aborts.current.set(key, abort);
        void done.then((outcome) => {
          aborts.current.delete(key);
          if (outcome.ok) {
            patch(key, {
              status: "ready",
              upload: outcome.upload,
              loaded: file.size,
            });
            setAnnouncement(`${name} is ready.`);
          } else if ("detail" in outcome) {
            patch(key, { status: "failed", detail: outcome.detail });
          }
        });
      });
    },
    [patch],
  );

  const remove = useCallback((key: string) => {
    aborts.current.get(key)?.();
    aborts.current.delete(key);
    setChips((all) => {
      const kept = all.filter((chip) => chip.key !== key);
      count.current = kept.length;
      return kept;
    });
    setNotice(null);
  }, []);

  /** After the question is sent: the composer starts empty again. */
  const clear = useCallback(() => {
    for (const abort of aborts.current.values()) abort();
    aborts.current.clear();
    count.current = 0;
    setChips([]);
    setNotice(null);
    setAnnouncement("");
  }, []);

  // Leaving the screen stops whatever is still uploading.
  useEffect(() => {
    const inFlight = aborts.current;
    return () => {
      for (const abort of inFlight.values()) abort();
    };
  }, []);

  const ready: Attached[] = chips.flatMap((chip) =>
    chip.status === "ready" && chip.upload
      ? [{ upload_id: chip.upload.upload_id, filename: chip.upload.filename }]
      : [],
  );
  const uploading = chips.some((chip) => chip.status === "uploading");
  return { chips, ready, uploading, notice, announcement, add, remove, clear };
}

/** The attached files above the composer: name, size, progress then Ready (or the refusal), and a remove button each. */
export function AttachmentChips({
  chips,
  notice,
  announcement,
  onRemove,
}: {
  chips: Chip[];
  notice: string | null;
  announcement: string;
  onRemove: (key: string) => void;
}) {
  return (
    <>
      {notice && (
        <p role="alert" className={styles.attachNotice}>
          {notice}
        </p>
      )}
      {chips.length > 0 && (
        <ul aria-label="Attached files" className={styles.chips}>
          {chips.map((chip) => (
            <li
              key={chip.key}
              className={styles.chip}
              data-status={chip.status}
            >
              <div className={styles.chipHead}>
                <span className={styles.chipName}>{chip.name}</span>
                <span className={styles.chipSize}>{formatSize(chip.size)}</span>
                <button
                  type="button"
                  className={styles.chipRemove}
                  aria-label={`Remove ${chip.name}`}
                  onClick={() => onRemove(chip.key)}
                >
                  <span aria-hidden="true">×</span>
                </button>
              </div>
              {chip.status === "uploading" && (
                <progress
                  className={styles.chipProgress}
                  aria-label={`Uploading ${chip.name}`}
                  max={chip.size || 1}
                  value={chip.loaded ?? undefined}
                />
              )}
              {chip.status === "ready" && (
                <div className={styles.chipBadges}>
                  <Badge tone="success">Ready</Badge>
                  {chip.upload?.injection && (
                    <Badge tone="warning">Instructions removed</Badge>
                  )}
                </div>
              )}
              {chip.status === "failed" && (
                <div className={styles.chipBadges}>
                  <Badge tone="danger">Not attached</Badge>
                  <p role="alert" className={styles.chipError}>
                    {chip.detail}
                  </p>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <InjectionAlert
        flags={chips.flatMap(({ status, upload }) =>
          status === "ready" && upload?.injection
            ? [
                {
                  ...upload.injection,
                  doc_id: upload.injection.doc_id ?? null,
                  title: upload.injection.title ?? null,
                  excerpt: upload.injection.excerpt ?? null,
                },
              ]
            : [],
        )}
      />
      <p aria-live="polite" className={styles.visuallyHidden}>
        {announcement}
      </p>
    </>
  );
}

/** A paperclip (decorative: the button is named "Attach files"). */
export function PaperclipIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}
