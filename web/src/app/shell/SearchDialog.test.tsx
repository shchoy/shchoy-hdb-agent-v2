import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import type { ConversationHit } from "@/lib/events";
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
function api(hits: ConversationHit[] = [ARREARS, LICENCE]) {
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
      return HttpResponse.json({ conversations: q.trim() ? hits : [] });
    }),
  );
  return queries;
}

const dialog = () => screen.getByRole("dialog", { name: "Search conversations" });
const field = () => within(dialog()).getByRole("combobox", { name: "Search conversations" });
/** The results once shown. */
const options = async () =>
  within(await within(dialog()).findByRole("listbox", { name: "Conversations" })).getAllByRole("option");

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

    await user.click(screen.getByRole("button", { name: /Search conversations/ }));
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
    expect(screen.queryByRole("dialog", { name: "Search conversations" })).toBeNull();
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

    expect(screen.queryByRole("dialog", { name: "Search conversations" })).toBeNull();
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
    await waitFor(() => expect(within(dialog()).getByRole("status")).toHaveTextContent("No conversations match"));

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
