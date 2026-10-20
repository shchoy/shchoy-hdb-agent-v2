/** BFF client for plg-api, typed from its OpenAPI document. Server only: never bundled for the browser. */
import "server-only";
import { NextResponse } from "next/server";
import createClient from "openapi-fetch";
import type { components, paths } from "@/lib/api/schema";
import type { UserCtx } from "@/lib/events";

export type { UserCtx };
export type RunRequest = components["schemas"]["RunRequest"];

const DEFAULT_PLG_API_URL = "http://127.0.0.1:8000";
/** plg-api trusts this header because it is only ever sent by the BFF over loopback. */
const USER_HEADER = "X-PLG-User";

/** The BFF's reply when plg-api can't be reached. */
export function plgApiUnavailable(): NextResponse {
  return NextResponse.json({ detail: "plg-api is unavailable" }, { status: 502 });
}

export function plgApiUrl(): string {
  return process.env.PLG_API_URL ?? DEFAULT_PLG_API_URL;
}

// Built per call so the base URL (and, in tests, the patched fetch) is read at request time.
function client() {
  return createClient<paths>({ baseUrl: plgApiUrl(), cache: "no-store" });
}

export async function listPersonas(): Promise<UserCtx[]> {
  const { data, error } = await client().GET("/personas");
  if (!data) throw new Error(`plg-api /personas failed: ${JSON.stringify(error)}`);
  return data;
}

/** The staff member for `staffId`, or null if plg-api doesn't recognise them. */
export async function getMe(staffId: string): Promise<UserCtx | null> {
  const { data, response } = await client().GET("/me", {
    params: { header: { "x-plg-user": staffId } },
  });
  if (data) return data;
  if (response.status === 401) return null;
  throw new Error(`plg-api /me failed with ${response.status}`);
}

/** Creates a thread; returns plg-api's status and JSON body so the BFF can relay them. */
export async function createThread(staffId: string): Promise<{ status: number; body: unknown }> {
  const { data, error, response } = await client().POST("/threads", {
    params: { header: { "x-plg-user": staffId } },
  });
  return { status: response.status, body: data ?? error };
}

type RunPath = "/threads/{thread_id}/runs";
type RunBody = paths[RunPath]["post"]["requestBody"]["content"]["application/json"];

/**
 * Starts a run. Uses fetch directly so the SSE body can be streamed through unread;
 * the request shape is still typed from the OpenAPI `paths`.
 */
export function startRun(
  staffId: string,
  threadId: string,
  body: RunBody,
  signal?: AbortSignal,
): Promise<Response> {
  const path: RunPath = "/threads/{thread_id}/runs";
  const url = plgApiUrl() + path.replace("{thread_id}", encodeURIComponent(threadId));
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      [USER_HEADER]: staffId,
    },
    body: JSON.stringify(body),
    cache: "no-store",
    signal,
  });
}

/** A source document as plain text blocks; plg-api's status and JSON body, for the BFF to relay. */
export async function getDocument(staffId: string, docId: string): Promise<{ status: number; body: unknown }> {
  const { data, error, response } = await client().GET("/documents/{doc_id}", {
    params: { path: { doc_id: docId }, header: { "x-plg-user": staffId } },
  });
  return { status: response.status, body: data ?? error };
}

/** Where a cited span (`start`:`end` of the chunk's text) sits in its document. */
export async function getChunkLocation(
  staffId: string,
  docId: string,
  chunkId: string,
  span: { start?: number; end?: number },
): Promise<{ status: number; body: unknown }> {
  const { data, error, response } = await client().GET("/documents/{doc_id}/chunks/{chunk_id}", {
    params: {
      path: { doc_id: docId, chunk_id: chunkId },
      query: span,
      header: { "x-plg-user": staffId },
    },
  });
  return { status: response.status, body: data ?? error };
}

/** A draft's DOCX file, unread, so the BFF can stream it through. */
export function getDraftFile(staffId: string, draftId: string): Promise<Response> {
  const path = "/drafts/{draft_id}/file";
  return fetch(plgApiUrl() + path.replace("{draft_id}", encodeURIComponent(draftId)), {
    headers: { [USER_HEADER]: staffId },
    cache: "no-store",
  });
}

/** The source file, unread, so the BFF can stream it through. */
export function getDocumentFile(staffId: string, docId: string): Promise<Response> {
  const path = "/documents/{doc_id}/file";
  return fetch(plgApiUrl() + path.replace("{doc_id}", encodeURIComponent(docId)), {
    headers: { [USER_HEADER]: staffId },
    cache: "no-store",
  });
}
