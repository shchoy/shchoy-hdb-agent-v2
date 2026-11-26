"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { MyDocument, MyDocuments as MyDocumentsView } from "@/lib/events";
import { Badge, Card, cardListClass, fieldsClass } from "../Card";
import { when } from "../dates";
import { ACTIVE_THREAD } from "../runClient";
import { refusalDetail, tidy } from "../shell/menu";
import { DocumentViewer } from "../SourceViewer";
import { ACCEPT, formatSize, uploadFile } from "../uploads";
import styles from "./library.module.css";

type Loaded = { status: "loading" } | { status: "failed"; error: string } | { status: "ok"; view: MyDocumentsView };

/** The most characters an upload's name may have (plg-api refuses more). */
const MAX_TITLE = 120;

const KIND_LABEL: Record<MyDocument["kind"], string> = {
  pdf: "PDF",
  docx: "Word",
  pptx: "PowerPoint",
  email: "Email",
  markdown: "Markdown",
  text: "Text",
  image: "Image",
};

/** A file being uploaded from this tab: its progress, then (if refused) why. */
type Sending = { key: string; name: string; size: number; loaded: number | null; detail?: string };

let nextKey = 0;

function failure(status: number): string {
  if (status === 401) return "You are no longer signed in. Sign in again.";
  return "Could not load your documents.";
}

/**
 * Library → My documents (#106): the officer's own uploads, each with its type, size, upload date and the conversations
 * that used it, against their space; files can be uploaded here without a conversation, and each one opened, renamed or
 * deleted (after a confirmation).
 */
export function MyDocuments() {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const [sending, setSending] = useState<Sending[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const picker = useRef<HTMLInputElement>(null);
  const uploadButton = useRef<HTMLButtonElement>(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/my-documents");
      if (!response.ok) return setLoaded({ status: "failed", error: failure(response.status) });
      setLoaded({ status: "ok", view: (await response.json()) as MyDocumentsView });
    } catch {
      setLoaded({ status: "failed", error: "Could not load your documents." });
    }
  }, []);

  useEffect(() => {
    // load() only sets state once plg-api has answered, never synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  function patch(key: string, change: Partial<Sending>) {
    setSending((all) => all.map((s) => (s.key === key ? { ...s, ...change } : s)));
  }

  async function send(files: File[]) {
    if (files.length === 0) return;
    const batch = files.map((file) => ({ file, key: `my-upload-${++nextKey}` }));
    // A new batch clears the refusals of the last one.
    setSending((all) => [
      ...all.filter((s) => !s.detail),
      ...batch.map(({ file, key }) => ({ key, name: file.name, size: file.size, loaded: null })),
    ]);
    await Promise.all(
      batch.map(async ({ file, key }) => {
        const outcome = await uploadFile(file, (sent) => patch(key, { loaded: sent })).done;
        if (outcome.ok) {
          setSending((all) => all.filter((s) => s.key !== key));
          setAnnouncement(`Uploaded ${outcome.upload.title}`);
        } else if (!("aborted" in outcome)) {
          patch(key, { detail: outcome.detail });
        }
      }),
    );
    await load();
  }

  const renamed = useCallback((item: MyDocument, title: string) => {
    setLoaded((was) =>
      was.status === "ok"
        ? {
            status: "ok",
            view: {
              ...was.view,
              uploads: was.view.uploads.map((u) => (u.upload_id === item.upload_id ? { ...u, title } : u)),
            },
          }
        : was,
    );
    setAnnouncement(`Renamed ${item.title} to ${title}`);
  }, []);

  const deleted = useCallback(
    (item: MyDocument) => {
      setAnnouncement(`Deleted ${item.title}`);
      uploadButton.current?.focus();
      void load();
    },
    [load],
  );

  return (
    <>
      <p aria-live="polite" className={styles.visuallyHidden}>
        {announcement}
      </p>
      {loaded.status === "loading" && <p role="status">Loading your documents…</p>}
      {loaded.status === "failed" && <p role="alert">{loaded.error}</p>}
      {loaded.status === "ok" && <Space used={loaded.view.used_bytes} quota={loaded.view.quota_bytes} />}
      <div className={styles.uploadBar}>
        <button ref={uploadButton} type="button" onClick={() => picker.current?.click()}>
          Upload files
        </button>
        <span className={styles.meta}>PDF, Word, text, Markdown, email or an image. Only you can see them.</span>
        <input
          ref={picker}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          tabIndex={-1}
          aria-label="Files to upload"
          onChange={(event) => {
            void send(Array.from(event.currentTarget.files ?? []));
            event.currentTarget.value = ""; // the same file can be picked again
          }}
        />
      </div>
      {sending.length > 0 && (
        <ul className={styles.sending} aria-label="Uploading">
          {sending.map((s) => (
            <li key={s.key}>
              {s.detail ? (
                <p role="alert" className={styles.refused}>
                  {s.name} was not uploaded: {s.detail}
                </p>
              ) : (
                <>
                  <span>
                    {s.name} ({formatSize(s.size)})
                  </span>
                  <progress
                    className={styles.progress}
                    aria-label={`Uploading ${s.name}`}
                    max={s.size || 1}
                    value={s.loaded ?? undefined}
                  />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {loaded.status === "ok" &&
        (loaded.view.uploads.length === 0 ? (
          <p className={styles.meta}>
            You haven&apos;t uploaded any documents yet. Upload files here, or attach them to a question on Ask.
          </p>
        ) : (
          <ul className={cardListClass} aria-label="My documents">
            {loaded.view.uploads.map((item) => (
              <li key={item.upload_id}>
                <UploadCard
                  item={item}
                  onRenamed={(title) => renamed(item, title)}
                  onDeleted={() => deleted(item)}
                  onStale={() => void load()}
                />
              </li>
            ))}
          </ul>
        ))}
    </>
  );
}

/** Space used against the officer's cap, in words and as a meter. */
function Space({ used, quota }: { used: number; quota: number }) {
  const id = useId();
  return (
    <div className={styles.space}>
      <p id={id} className={styles.spaceText}>
        {formatSize(used)} of {formatSize(quota)} used
      </p>
      <meter className={styles.meter} aria-labelledby={id} min={0} max={quota} low={quota * 0.8} high={quota * 0.95} value={used} />
    </div>
  );
}

type Mode = "idle" | "rename" | "confirm";

/** One upload: what it is, where it was used, and Open / Rename / Delete. */
function UploadCard({
  item,
  onRenamed,
  onDeleted,
  onStale,
}: {
  item: MyDocument;
  onRenamed(title: string): void;
  onDeleted(): void;
  /** plg-api no longer has it (404): the list reloads. */
  onStale(): void;
}) {
  const [mode, setMode] = useState<Mode>("idle");
  const [title, setTitle] = useState(item.title);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const renameButton = useRef<HTMLButtonElement>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const back = useRef<"rename" | "delete" | null>(null);
  const id = useId();
  const url = `/api/uploads/${encodeURIComponent(item.upload_id)}`;

  useEffect(() => {
    if (mode === "rename") {
      field.current?.focus();
      field.current?.select();
    } else if (mode === "confirm") cancel.current?.focus();
    else if (back.current) {
      (back.current === "rename" ? renameButton : deleteButton).current?.focus();
      back.current = null;
    }
  }, [mode]);

  function close(from: "rename" | "delete") {
    back.current = from;
    setMode("idle");
  }

  function cancelChange() {
    setError(null);
    close(mode === "confirm" ? "delete" : "rename");
  }

  function onEscape(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    cancelChange();
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    const next = tidy(title);
    if (!next) return setError("Give the document a name.");
    if (next === item.title) return cancelChange();
    setWorking(true);
    try {
      const response = await fetch(url, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: next }),
      });
      if (!response.ok) {
        setError(await refusalDetail(response, "The document couldn't be renamed."));
        if (response.status === 404) onStale();
        return;
      }
      setError(null);
      onRenamed(next);
      close("rename");
    } catch {
      setError("The document couldn't be renamed. Try again.");
    } finally {
      setWorking(false);
    }
  }

  async function remove() {
    setWorking(true);
    try {
      const response = await fetch(url, { method: "DELETE" });
      if (!response.ok) {
        setError(await refusalDetail(response, "The document couldn't be deleted."));
        if (response.status === 404) onStale();
        return;
      }
      onDeleted();
    } catch {
      setError("The document couldn't be deleted. Try again.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <Card
      as="article"
      level={2}
      heading={item.title}
      badges={
        <>
          <Badge>{KIND_LABEL[item.kind]}</Badge>
          {item.injection && <Badge tone="warning">Instructions removed</Badge>}
        </>
      }
    >
      <dl className={fieldsClass}>
        <dt>File</dt>
        <dd className={styles.filename}>{item.filename}</dd>
        <dt>Size</dt>
        <dd>{formatSize(item.size)}</dd>
        <dt>Uploaded</dt>
        <dd>{when(item.uploaded_at)}</dd>
        <dt>Used in</dt>
        <dd>
          {item.conversations.length === 0 ? (
            "Not used in a conversation yet"
          ) : (
            <ul className={styles.conversations} aria-label={`Conversations that used ${item.title}`}>
              {item.conversations.map((c) => (
                <li key={c.thread_id}>
                  <Link href="/" onClick={() => sessionStorage.setItem(ACTIVE_THREAD, c.thread_id)}>
                    {c.title}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
      {item.injection && (
        <p role="note" className={styles.warning}>
          Instructions planted in this file for the assistant were removed when it was uploaded, and are ignored.
        </p>
      )}
      {mode === "rename" ? (
        <form className={styles.renameForm} onSubmit={rename} onKeyDown={onEscape}>
          <label htmlFor={`${id}-title`}>Name</label>
          <input
            ref={field}
            id={`${id}-title`}
            value={title}
            maxLength={MAX_TITLE}
            onChange={(e) => setTitle(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-error` : undefined}
          />
          <div className={styles.actions}>
            <button type="submit" disabled={working}>
              Save
            </button>
            <button type="button" onClick={cancelChange}>
              Cancel
            </button>
          </div>
          {error && (
            <p id={`${id}-error`} role="alert" className={styles.refused}>
              {error}
            </p>
          )}
        </form>
      ) : mode === "confirm" ? (
        <div role="group" aria-labelledby={`${id}-confirm`} className={styles.confirm} onKeyDown={onEscape}>
          <p id={`${id}-confirm`} className={styles.confirmText}>
            Delete {item.title}?
          </p>
          <p>It leaves your searches for good. Answers that cited it keep the citation, shown as removed.</p>
          <div className={styles.actions}>
            <button type="button" data-variant="danger-solid" disabled={working} onClick={() => void remove()}>
              Delete
            </button>
            <button ref={cancel} type="button" onClick={cancelChange}>
              Cancel
            </button>
          </div>
          {error && (
            <p role="alert" className={styles.refused}>
              {error}
            </p>
          )}
        </div>
      ) : (
        <>
          <div className={styles.actions}>
            <DocumentViewer docId={item.upload_id} label={`Open ${item.title}`} />
            <button
              ref={renameButton}
              type="button"
              aria-label={`Rename ${item.title}`}
              onClick={() => {
                setError(null);
                setTitle(item.title);
                setMode("rename");
              }}
            >
              Rename
            </button>
            <button
              ref={deleteButton}
              type="button"
              data-variant="danger"
              aria-label={`Delete ${item.title}`}
              onClick={() => {
                setError(null);
                setMode("confirm");
              }}
            >
              Delete
            </button>
          </div>
          {error && (
            <p role="alert" className={styles.refused}>
              {error}
            </p>
          )}
        </>
      )}
    </Card>
  );
}
