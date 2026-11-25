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

type Thread = { thread_id: string; title: string; updated_at: string };

/** plg-api's conversations, renamed and deleted as the BFF is asked to; every request is recorded. */
function api(refuseDelete?: { status: number; detail: string }) {
  let threads: Thread[] = [
    { thread_id: "t9", title: "What is a letter of demand?", updated_at: "2026-11-02T10:00:00Z" },
    { thread_id: "t8", title: "Arrears for Cendana", updated_at: "2026-11-01T10:00:00Z" },
  ];
  const requests: string[] = [];
  server.use(
    http.get("/api/threads", () => HttpResponse.json(threads)),
    http.get("/api/approvals", () => HttpResponse.json([])),
    http.patch("/api/threads/:id", async ({ params, request }) => {
      const { title } = (await request.json()) as { title: string };
      requests.push(`PATCH ${String(params.id)} ${title}`);
      threads = threads.map((t) => (t.thread_id === params.id ? { ...t, title } : t));
      return HttpResponse.json(threads.find((t) => t.thread_id === params.id));
    }),
    http.delete("/api/threads/:id", ({ params }) => {
      requests.push(`DELETE ${String(params.id)}`);
      if (refuseDelete) return HttpResponse.json({ detail: refuseDelete.detail }, { status: refuseDelete.status });
      threads = threads.filter((t) => t.thread_id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return requests;
}

function conversations() {
  return screen.getByRole("navigation", { name: "Conversations" });
}

async function openMenu(user: ReturnType<typeof userEvent.setup>, title: string) {
  const button = await within(conversations()).findByRole("button", { name: `Options for ${title}` });
  await user.click(button);
  return button;
}

beforeEach(() => {
  sessionStorage.clear();
  navigation.pathname = "/library";
  navigation.push.mockReset();
});

describe("Conversation menu", () => {
  it("offers Rename, Pin, Move to group… and Delete, operable by keyboard; Escape closes it back to its button", async () => {
    api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    const button = await within(conversations()).findByRole("button", { name: "Options for Arrears for Cendana" });
    expect(button).toHaveAttribute("aria-haspopup", "menu");

    button.focus();
    await user.keyboard("{Enter}");

    const menu = screen.getByRole("menu", { name: "Arrears for Cendana" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Rename", "Pin", "Move to group…", "Delete"]);
    expect(items[0]).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(items[1]).toHaveFocus();
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(items[3]).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(items[0]).toHaveFocus();
    await user.keyboard("{End}");
    expect(items[3]).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("renames a conversation: the sidebar shows the new title", async () => {
    const requests = api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await openMenu(user, "Arrears for Cendana");

    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const field = within(conversations()).getByRole("textbox", { name: "Conversation title" });
    expect(field).toHaveValue("Arrears for Cendana");
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "Cendana arrears 2026{Enter}");

    expect(await within(conversations()).findByRole("button", { name: "Cendana arrears 2026" })).toBeInTheDocument();
    expect(requests).toEqual(["PATCH t8 Cendana arrears 2026"]);
    expect(screen.getByRole("status", { name: "Conversation updates" })).toHaveTextContent(
      "Renamed to Cendana arrears 2026",
    );
    expect(within(conversations()).getByRole("button", { name: "Options for Cendana arrears 2026" })).toHaveFocus();
  });

  it("cancels a rename on Escape, changing nothing", async () => {
    const requests = api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await openMenu(user, "Arrears for Cendana");
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));

    await user.type(within(conversations()).getByRole("textbox", { name: "Conversation title" }), " x{Escape}");

    expect(within(conversations()).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(conversations()).getByRole("button", { name: "Arrears for Cendana" })).toBeInTheDocument();
    expect(within(conversations()).getByRole("button", { name: "Options for Arrears for Cendana" })).toHaveFocus();
    expect(requests).toEqual([]);
  });

  it("deletes a conversation only once confirmed", async () => {
    const requests = api();
    const user = userEvent.setup();
    sessionStorage.setItem("plg_active_thread", "t8");
    render(inShell(<p>screen</p>));
    await openMenu(user, "Arrears for Cendana");

    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const confirm = within(conversations()).getByRole("group", { name: "Delete Arrears for Cendana?" });
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(requests).toEqual([]);
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(within(conversations()).queryByRole("button", { name: "Arrears for Cendana" })).not.toBeInTheDocument(),
    );
    expect(requests).toEqual(["DELETE t8"]);
    expect(screen.getByRole("status", { name: "Conversation updates" })).toHaveTextContent(
      "Deleted Arrears for Cendana",
    );
    expect(sessionStorage.getItem("plg_active_thread")).toBeNull();
  });

  it("keeps the conversation when the deletion is cancelled", async () => {
    const requests = api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    const button = await openMenu(user, "Arrears for Cendana");
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));

    await user.click(within(conversations()).getByRole("button", { name: "Cancel" }));

    expect(within(conversations()).queryByRole("group")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
    expect(requests).toEqual([]);
  });

  it("says why a deletion is refused and keeps the conversation", async () => {
    const detail = "This conversation has an action awaiting approval: approve or reject it first, then delete it";
    api({ status: 409, detail });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await openMenu(user, "Arrears for Cendana");
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));

    await user.click(within(conversations()).getByRole("button", { name: "Delete" }));

    expect(await within(conversations()).findByRole("alert")).toHaveTextContent(detail);
    expect(within(conversations()).getByRole("button", { name: "Arrears for Cendana" })).toBeInTheDocument();
  });

  it("works in the phone drawer: Escape closes the menu, not the drawer", async () => {
    api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.click(screen.getByRole("button", { name: "Menu" }));
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    await user.click(await within(drawer).findByRole("button", { name: "Options for Arrears for Cendana" }));

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();
  });
});
