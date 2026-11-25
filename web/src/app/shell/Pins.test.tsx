import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw";
import { inShell } from "@/test/shell";

const navigation = vi.hoisted(() => ({ pathname: "/library", push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, refresh: navigation.refresh }),
}));

type Thread = { thread_id: string; title: string; updated_at: string; group_id: string | null; pinned: number | null };
type Group = { group_id: string; name: string; pinned: number | null };

const thread = (thread_id: string, title: string, extra: Partial<Thread> = {}): Thread => ({
  thread_id,
  title,
  updated_at: `2026-11-0${thread_id.slice(1)}T10:00:00Z`,
  group_id: null,
  pinned: null,
  ...extra,
});

/** plg-api's conversations and groups, pinned as the BFF is asked to (pin order = the order pinned); pins recorded. */
function api(start: { threads: Thread[]; groups?: Group[]; refusePin?: boolean }) {
  let threads = start.threads;
  let groups = start.groups ?? [];
  const requests: string[] = [];
  const next = () => Math.max(-1, ...[...threads, ...groups].map((i) => i.pinned ?? -1)) + 1;
  server.use(
    http.get("/api/threads", () => HttpResponse.json(threads)),
    http.get("/api/approvals", () => HttpResponse.json([])),
    http.get("/api/groups", () => HttpResponse.json(groups)),
    http.put("/api/threads/:id/pin", async ({ params, request }) => {
      const { pinned } = (await request.json()) as { pinned: boolean };
      requests.push(`PIN ${String(params.id)} ${pinned}`);
      if (start.refusePin) return HttpResponse.json({ detail: "Thread not found" }, { status: 404 });
      threads = threads.map((t) => (t.thread_id === params.id ? { ...t, pinned: pinned ? (t.pinned ?? next()) : null } : t));
      return HttpResponse.json(threads.find((t) => t.thread_id === params.id));
    }),
    http.put("/api/groups/:id/pin", async ({ params, request }) => {
      const { pinned } = (await request.json()) as { pinned: boolean };
      requests.push(`PIN group ${String(params.id)} ${pinned}`);
      groups = groups.map((g) => (g.group_id === params.id ? { ...g, pinned: pinned ? (g.pinned ?? next()) : null } : g));
      return HttpResponse.json(groups.find((g) => g.group_id === params.id));
    }),
  );
  return requests;
}

const conversations = () => screen.getByRole("navigation", { name: "Conversations" });
const pinnedList = () => screen.queryByRole("list", { name: "Pinned" });
const recent = () => screen.getByRole("list", { name: "Recent conversations" });
const announced = () => screen.getByRole("status", { name: "Conversation updates" });
/** The conversation titles and group names a list shows, in order. */
const items = (list: HTMLElement) =>
  within(list)
    .queryAllByRole("button", { name: /^(?!Options)/ })
    .map((b) => b.textContent?.replace(/\d.*$/, "")); // a group: its name (then its count)

async function choose(user: ReturnType<typeof userEvent.setup>, options: string, item: string) {
  await user.click(await within(conversations()).findByRole("button", { name: options }));
  await user.click(screen.getByRole("menuitem", { name: item }));
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

describe("Pinned conversations and groups (#102)", () => {
  it("shows no Pinned section while nothing is pinned", async () => {
    api({ threads: [thread("t2", "Arrears for Cendana"), thread("t1", "What is a letter of demand?")] });
    render(inShell(<p>screen</p>));

    expect(await within(conversations()).findByRole("button", { name: "Arrears for Cendana" })).toBeInTheDocument();
    expect(pinnedList()).toBeNull();
    expect(within(conversations()).queryByRole("heading", { name: "Pinned" })).toBeNull();
  });

  it("pins a conversation from its menu: only in Pinned, announced, focus on its Options there", async () => {
    const requests = api({ threads: [thread("t2", "Arrears for Cendana"), thread("t1", "What is a letter of demand?")] });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await choose(user, "Options for Arrears for Cendana", "Pin");

    await waitFor(() => expect(pinnedList()).not.toBeNull());
    expect(items(pinnedList()!)).toEqual(["Arrears for Cendana"]);
    expect(items(recent())).toEqual(["What is a letter of demand?"]);
    expect(requests).toEqual(["PIN t2 true"]);
    expect(announced()).toHaveTextContent("Pinned Arrears for Cendana");
    expect(within(pinnedList()!).getByRole("button", { name: "Options for Arrears for Cendana" })).toHaveFocus();
  });

  it("unpinning puts a conversation back in its group", async () => {
    const requests = api({
      threads: [thread("t2", "Arrears for Cendana", { group_id: "g1", pinned: 0 }), thread("t1", "Renewal question", { group_id: "g1" })],
      groups: [{ group_id: "g1", name: "Arrears", pinned: null }],
    });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await waitFor(() => expect(pinnedList()).not.toBeNull());
    expect(items(pinnedList()!)).toEqual(["Arrears for Cendana"]);
    expect(items(screen.getByRole("list", { name: "Arrears" }))).toEqual(["Renewal question"]);
    expect(screen.getByRole("button", { name: "Arrears, 1 conversation" })).toBeInTheDocument();

    await choose(user, "Options for Arrears for Cendana", "Unpin");

    await waitFor(() => expect(pinnedList()).toBeNull());
    expect(items(screen.getByRole("list", { name: "Arrears" }))).toEqual(["Arrears for Cendana", "Renewal question"]);
    expect(requests).toEqual(["PIN t2 false"]);
    expect(announced()).toHaveTextContent("Unpinned Arrears for Cendana");
    expect(screen.getByRole("button", { name: "Options for Arrears for Cendana" })).toHaveFocus();
  });

  it("pins a group: it shows in Pinned with its conversations, no longer under Groups", async () => {
    const requests = api({
      threads: [thread("t2", "Arrears for Cendana", { group_id: "g1" }), thread("t1", "What is a letter of demand?")],
      groups: [
        { group_id: "g1", name: "Arrears", pinned: null },
        { group_id: "g2", name: "Renewals", pinned: null },
      ],
    });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await choose(user, "Options for group Arrears", "Pin group");

    await waitFor(() => expect(pinnedList()).not.toBeNull());
    const pinned = pinnedList()!;
    expect(within(pinned).getByRole("button", { name: "Arrears, 1 conversation" })).toBeInTheDocument();
    expect(items(within(pinned).getByRole("list", { name: "Arrears" }))).toEqual(["Arrears for Cendana"]);
    expect(within(screen.getByRole("list", { name: "Groups" })).queryByRole("button", { name: /^Arrears,/ })).toBeNull();
    expect(requests).toEqual(["PIN group g1 true"]);
    expect(announced()).toHaveTextContent("Pinned group Arrears");
    expect(within(pinned).getByRole("button", { name: "Options for group Arrears" })).toHaveFocus();

    await choose(user, "Options for group Arrears", "Unpin group");

    await waitFor(() => expect(pinnedList()).toBeNull());
    expect(screen.getByRole("button", { name: "Arrears, 1 conversation" })).toBeInTheDocument();
    expect(announced()).toHaveTextContent("Unpinned group Arrears");
  });

  it("a pinned conversation moved to a group stays in Pinned, says so, and goes there once unpinned; it isn't draggable", async () => {
    let groupOf: string | null = null;
    api({ threads: [thread("t2", "Arrears for Cendana", { pinned: 0 })], groups: [{ group_id: "g1", name: "Arrears", pinned: null }] });
    server.use(
      http.put("/api/threads/:id/group", async ({ request }) => {
        groupOf = ((await request.json()) as { group_id: string | null }).group_id;
        return HttpResponse.json({ ...thread("t2", "Arrears for Cendana", { pinned: 0 }), group_id: groupOf });
      }),
    );
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await waitFor(() => expect(pinnedList()).not.toBeNull());
    const row = within(pinnedList()!).getByRole("button", { name: "Arrears for Cendana" }).parentElement!;
    expect(row).not.toHaveAttribute("draggable");

    await choose(user, "Options for Arrears for Cendana", "Move to group…");
    await user.click(screen.getByRole("menuitemradio", { name: "Arrears" }));

    expect(await screen.findByText("Moved Arrears for Cendana to Arrears. It stays pinned.")).toBeInTheDocument();
    expect(groupOf).toBe("g1");
    expect(items(pinnedList()!)).toEqual(["Arrears for Cendana"]);
    expect(screen.getByRole("button", { name: "Arrears, 0 conversations" })).toBeInTheDocument();

    await choose(user, "Options for Arrears for Cendana", "Unpin");

    await waitFor(() => expect(pinnedList()).toBeNull());
    expect(items(screen.getByRole("list", { name: "Arrears" }))).toEqual(["Arrears for Cendana"]);
  });

  it("lists pinned conversations and groups together in pin order", async () => {
    api({
      threads: [
        thread("t3", "Newest", { pinned: 2 }),
        thread("t2", "Middle", { pinned: 0 }),
        thread("t1", "In a pinned conversation group", { group_id: "g1" }),
      ],
      groups: [{ group_id: "g1", name: "Arrears", pinned: 1 }],
    });
    render(inShell(<p>screen</p>));

    await waitFor(() => expect(pinnedList()).not.toBeNull());
    expect(items(pinnedList()!)).toEqual(["Middle", "Arrears", "In a pinned conversation group", "Newest"]);
  });

  it("shows plg-api's refusal and keeps the conversation where it was", async () => {
    api({ threads: [thread("t2", "Arrears for Cendana")], refusePin: true });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await choose(user, "Options for Arrears for Cendana", "Pin");

    expect(await screen.findByRole("alert")).toHaveTextContent("Thread not found");
    expect(pinnedList()).toBeNull();
    expect(items(recent())).toEqual(["Arrears for Cendana"]);
  });
});
