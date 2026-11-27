import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import type { ConversationHit, DocumentHit } from "@/lib/events";
import { documentFixture } from "@/test/documents";
import { server } from "@/test/msw";
import { inShell } from "@/test/shell";

const navigation = vi.hoisted(() => ({ pathname: "/library", push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, refresh: navigation.refresh }),
}));

const ARREARS: ConversationHit = {
  thread_id: "t1",
  title: "Lucky Star arrears",
  updated_at: "2026-11-20T01:00:00+00:00",
  group_id: "g1",
  group_name: "Arrears",
  pinned: 0,
  matched: "answer",
  message_index: 2,
  snippet: [{ text: "…the ", match: false }, { text: "arrears", match: true }, { text: " are S$4,000…", match: false }],
};

const LICENCE: ConversationHit = {
  thread_id: "t2",
  title: "Licence renewals",
  updated_at: "2026-11-19T01:00:00+00:00",
  group_id: null,
  group_name: null,
  pinned: null,
  matched: "title",
  message_index: null,
  snippet: [{ text: "Licence renewals", match: false }],
};

/** plg-api's search (records each query) and a sidebar holding both conversations. */
function api(hits: ConversationHit[] = [ARREARS, LICENCE], documents: DocumentHit[] = [], uploads: DocumentHit[] = []) {
  const queries: string[] = [];
  server.use(
    http.get("/api/threads", () =>
      HttpResponse.json([
        { thread_id: "t1", title: ARREARS.title, updated_at: ARREARS.updated_at, group_id: "g1", pinned: null },
        { thread_id: "t2", title: LICENCE.title, updated_at: LICENCE.updated_at, group_id: null, pinned: null },
      ]),
    ),
    http.get("/api/groups", () => HttpResponse.json([{ group_id: "g1", name: "Arrears", pinned: null }])),
    http.get("/api/approvals", () => HttpResponse.json([])),
    http.get("/api/search", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q") ?? "";
      queries.push(q);
      return HttpResponse.json(
        q.trim() ? { conversations: hits, documents, uploads } : { conversations: [], documents: [], uploads: [] },
      );
    }),
  );
  return queries;
}

const dialog = () => screen.getByRole("dialog", { name: "Search" });
const field = () => within(dialog()).getByRole("combobox", { name: "Search" });
/** The results once shown (all groups, in order). */
const options = async () =>
  within(await within(dialog()).findByRole("listbox", { name: "Search results" })).getAllByRole("option");
/** One group's results. */
const group = (name: string) =>
  within(within(dialog()).getByRole("group", { name })).getAllByRole("option");

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  navigation.pathname = "/library";
  navigation.push.mockReset();
});

describe("Search conversations (#107)", () => {
  it("opens from the sidebar box, shows results as the officer types, with snippet, group and pin", async () => {
    const queries = api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await user.click(screen.getByRole("button", { name: /^Search/ }));
    expect(field()).toHaveFocus();
    await user.type(field(), "arrears");

    const [first, second] = await options();
    expect(first).toHaveTextContent("Lucky Star arrears");
    expect(first.querySelector("mark")).toHaveTextContent("arrears");
    expect(first).toHaveTextContent("Pinned · group Arrears");
    expect(second).toHaveTextContent("Licence renewals");
    expect(second).toHaveTextContent("In Recent");
    expect(within(dialog()).getByRole("status")).toHaveTextContent("2 conversations found");
    expect(queries.at(-1)).toBe("arrears");
  });

  it("opens with Ctrl+K or ⌘K, and Escape closes it, focus back where it was", async () => {
    api();
    const user = userEvent.setup();
    render(inShell(<button type="button">Somewhere</button>));
    const somewhere = screen.getByRole("button", { name: "Somewhere" });
    somewhere.focus();

    await user.keyboard("{Control>}k{/Control}");
    expect(field()).toHaveFocus();
    await user.keyboard("{Control>}k{/Control}"); // again while open: still where it was opened from
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Search" })).toBeNull();
    expect(somewhere).toHaveFocus();

    await user.keyboard("{Meta>}k{/Meta}");
    expect(field()).toHaveFocus();
  });

  it("arrows through the results and opens one with Enter, at its turn", async () => {
    api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "arrears");
    const [first, second] = await options();

    expect(first).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}");
    expect(field()).toHaveAttribute("aria-activedescendant", second.id);
    expect(second).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}"); // wraps
    expect(field()).toHaveAttribute("aria-activedescendant", first.id);
    await user.keyboard("{ArrowUp}");
    expect(field()).toHaveAttribute("aria-activedescendant", second.id);
    await user.keyboard("{ArrowUp}{Enter}");

    expect(screen.queryByRole("dialog", { name: "Search" })).toBeNull();
    expect(sessionStorage.getItem("plg_active_thread")).toBe("t1");
    expect(sessionStorage.getItem("plg_active_turn")).toBe("2");
    expect(navigation.push).toHaveBeenCalledWith("/");
  });

  it("says when nothing matches, and when search isn't available", async () => {
    api([]);
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "zebra");
    await waitFor(() => expect(within(dialog()).getByRole("status")).toHaveTextContent("Nothing matches “zebra”"));

    server.use(http.get("/api/search", () => HttpResponse.json({ detail: "down" }, { status: 503 })));
    await user.type(field(), "s");
    expect(await within(dialog()).findByRole("alert")).toHaveTextContent("Search isn't available");
  });

  it("opens a conversation on the Ask screen at the matching turn and highlights it in the sidebar", async () => {
    navigation.pathname = "/";
    api();
    localStorage.setItem("plg_collapsed_groups", JSON.stringify(["g1"])); // its group is collapsed
    server.use(
      http.get("/api/threads/t1", () =>
        HttpResponse.json({
          thread_id: "t1",
          title: ARREARS.title,
          summary: "",
          messages: [
            { role: "user", content: "What is owed at Lucky Star?" },
            { role: "assistant", content: "Nothing yet." },
            { role: "user", content: "And now?" },
            { role: "assistant", content: "Now the arrears are S$4,000." },
            { role: "user", content: "Thanks" },
            { role: "assistant", content: "You're welcome." },
          ],
        }),
      ),
      http.get("/api/threads/:id/runs/latest", () => HttpResponse.json({ detail: "none" }, { status: 404 })),
    );
    const user = userEvent.setup();
    render(inShell(<AskScreen />));
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "arrears");
    await options();
    await user.keyboard("{Enter}");

    const history = await screen.findByRole("list", { name: "Earlier in this conversation" });
    const turn = await within(history).findByText("And now?");
    await waitFor(() => expect(turn.closest("li")).toHaveFocus());
    expect(turn.closest("li")).toHaveAttribute("data-found");
    const sidebar = screen.getByRole("navigation", { name: "Conversations" });
    expect(within(sidebar).getByRole("button", { name: ARREARS.title })).toHaveAttribute("aria-current", "true");
  });
});

const DOCX = documentFixture("docx");
const UPLOAD = documentFixture("upload");

/** A Library document's content match, at the recorded docx fixture's span. */
const POLICY: DocumentHit = {
  doc_id: DOCX.document.doc_id,
  chunk_id: DOCX.location.chunk_id,
  title: DOCX.document.title,
  doc_type: "policy",
  version: "2.1",
  status: "current",
  location: DOCX.location.location,
  upload: false,
  matched: "content",
  snippet: [{ text: "…on renewal, the ", match: false }, { text: "deposit", match: true }, { text: " is…", match: false }],
  span: { start: DOCX.start, end: DOCX.end },
};

const OLD_POLICY: DocumentHit = {
  ...POLICY,
  doc_id: "SP-old",
  chunk_id: "SP-old#000",
  version: "2.0",
  status: "superseded",
};

const NOTE: DocumentHit = {
  doc_id: UPLOAD.document.doc_id,
  chunk_id: UPLOAD.location.chunk_id,
  title: UPLOAD.document.title,
  doc_type: "upload",
  version: null,
  status: "current",
  location: UPLOAD.location.location,
  upload: true,
  matched: "content",
  snippet: [{ text: "the ", match: false }, { text: "deposit", match: true }],
  span: { start: UPLOAD.start, end: UPLOAD.end },
};

/** plg-api's source documents for the docx and upload fixtures. */
function documents() {
  const located: string[] = [];
  server.use(
    http.get("/api/documents/:id", ({ params }) =>
      HttpResponse.json(params.id === NOTE.doc_id ? UPLOAD.document : DOCX.document),
    ),
    http.get("/api/documents/:id/chunks/:chunk", ({ params, request }) => {
      located.push(`${String(params.chunk)}?${new URL(request.url).searchParams}`);
      return HttpResponse.json(params.id === NOTE.doc_id ? UPLOAD.location : DOCX.location);
    }),
  );
  return located;
}

describe("Search documents and uploads (#108)", () => {
  it("groups results by type: conversations, documents (superseded badged), then the officer's uploads", async () => {
    api([ARREARS], [POLICY, OLD_POLICY], [NOTE]);
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "deposit");
    await options();

    expect(group("Conversations")).toHaveLength(1);
    const [current, old] = group("Documents");
    expect(current).toHaveTextContent(`${POLICY.title} v2.1`);
    expect(current.querySelector("mark")).toHaveTextContent("deposit");
    expect(within(current).queryByText("Superseded")).toBeNull();
    expect(within(old).getByText("Superseded")).toBeInTheDocument();
    const [note] = group("My uploads");
    expect(note).toHaveTextContent(NOTE.title);
    expect(note).toHaveTextContent("Your upload");
    expect(within(dialog()).getByRole("status")).toHaveTextContent("1 conversation, 2 documents and 1 upload found");
  });

  it("arrows move across groups, and Enter opens a document in the source viewer with the match highlighted", async () => {
    api([ARREARS], [POLICY], [NOTE]);
    const located = documents();
    const user = userEvent.setup();
    render(inShell(<button type="button">Somewhere</button>));
    const somewhere = screen.getByRole("button", { name: "Somewhere" });
    somewhere.focus();
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "deposit");
    const [, policy] = await options();

    await user.keyboard("{ArrowDown}");
    expect(field()).toHaveAttribute("aria-activedescendant", policy.id);
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("dialog", { name: "Search" })).toBeNull();
    const viewer = await screen.findByRole("region", { name: `Source: ${POLICY.title}` });
    expect(viewer.querySelector("mark")).toHaveTextContent(DOCX.location.quote.slice(0, 20));
    expect(located).toEqual([`${POLICY.chunk_id}?start=${DOCX.start}&end=${DOCX.end}`]);
    expect(screen.getByRole("dialog", { name: `Search result: ${POLICY.title}` })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: `Source: ${POLICY.title}` })).toBeNull();
    expect(somewhere).toHaveFocus();
  });

  it("opens the officer's own upload by click, badged as theirs", async () => {
    api([], [], [NOTE]);
    documents();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "deposit");
    const [note] = await options();

    await user.click(note);

    const viewer = await screen.findByRole("region", { name: `Source: ${NOTE.title}` });
    expect(within(viewer).getByText("Your upload")).toBeInTheDocument();
    expect(viewer.querySelector("mark")).not.toBeNull();
    await user.click(within(viewer).getByRole("button", { name: "Close source" }));
    expect(screen.queryByRole("region", { name: `Source: ${NOTE.title}` })).toBeNull();
  });

  it("opens a title match from the top, with nothing highlighted", async () => {
    api([], [{ ...POLICY, matched: "title", span: null, snippet: [{ text: POLICY.title, match: true }] }]);
    const located = documents();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.keyboard("{Control>}k{/Control}");
    await user.type(field(), "tenancy");
    await options();
    await user.keyboard("{Enter}");

    const viewer = await screen.findByRole("region", { name: `Source: ${POLICY.title}` });
    expect(viewer.querySelector("mark")).toBeNull();
    expect(located).toEqual([]);
  });
});
