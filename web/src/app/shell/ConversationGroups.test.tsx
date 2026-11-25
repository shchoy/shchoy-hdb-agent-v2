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

type Thread = { thread_id: string; title: string; updated_at: string; group_id: string | null };
type Group = { group_id: string; name: string };

/** plg-api's conversations and groups, changed as the BFF is asked to; every changing request is recorded. */
function api(start: { groups?: Group[]; threads?: Thread[]; refuseMove?: string } = {}) {
  let groups: Group[] = start.groups ?? [];
  let threads: Thread[] = start.threads ?? [
    { thread_id: "t9", title: "What is a letter of demand?", updated_at: "2026-11-02T10:00:00Z", group_id: null },
    { thread_id: "t8", title: "Arrears for Cendana", updated_at: "2026-11-01T10:00:00Z", group_id: null },
  ];
  const requests: string[] = [];
  server.use(
    http.get("/api/threads", () => HttpResponse.json(threads)),
    http.get("/api/approvals", () => HttpResponse.json([])),
    http.get("/api/groups", () => HttpResponse.json(groups)),
    http.post("/api/groups", async ({ request }) => {
      const { name } = (await request.json()) as { name: string };
      requests.push(`POST ${name}`);
      const group = { group_id: `g${groups.length + 1}`, name };
      groups = [...groups, group];
      return HttpResponse.json(group, { status: 201 });
    }),
    http.patch("/api/groups/:id", async ({ params, request }) => {
      const { name } = (await request.json()) as { name: string };
      requests.push(`PATCH ${String(params.id)} ${name}`);
      groups = groups.map((g) => (g.group_id === params.id ? { ...g, name } : g));
      return HttpResponse.json(groups.find((g) => g.group_id === params.id));
    }),
    http.delete("/api/groups/:id", ({ params }) => {
      requests.push(`DELETE group ${String(params.id)}`);
      groups = groups.filter((g) => g.group_id !== params.id);
      threads = threads.map((t) => (t.group_id === params.id ? { ...t, group_id: null } : t));
      return new HttpResponse(null, { status: 204 });
    }),
    http.put("/api/threads/:id/group", async ({ params, request }) => {
      const { group_id } = (await request.json()) as { group_id: string | null };
      requests.push(`MOVE ${String(params.id)} ${group_id}`);
      if (start.refuseMove) return HttpResponse.json({ detail: start.refuseMove }, { status: 404 });
      threads = threads.map((t) => (t.thread_id === params.id ? { ...t, group_id } : t));
      return HttpResponse.json(threads.find((t) => t.thread_id === params.id));
    }),
    http.delete("/api/threads/:id", ({ params }) => {
      requests.push(`DELETE ${String(params.id)}`);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return requests;
}

const conversations = () => screen.getByRole("navigation", { name: "Conversations" });
const recent = () => screen.getByRole("list", { name: "Recent conversations" });
const group = (name: string) => screen.getByRole("list", { name });
const announced = () => screen.getByRole("status", { name: "Conversation updates" });
const titles = (list: HTMLElement) =>
  within(list)
    .queryAllByRole("button", { name: /^(?!Options)/ })
    .map((b) => b.textContent);

async function moveTo(user: ReturnType<typeof userEvent.setup>, title: string, destination: string) {
  await user.click(await within(conversations()).findByRole("button", { name: `Options for ${title}` }));
  await user.click(screen.getByRole("menuitem", { name: "Move to group…" }));
  await user.click(screen.getByRole("menuitemradio", { name: destination }));
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  navigation.pathname = "/library";
});

describe("Conversation groups", () => {
  it("creates a group from New group, announced, focus back on New group", async () => {
    const requests = api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    const create = await within(conversations()).findByRole("button", { name: "New group" });
    await user.click(create);
    await user.keyboard("  Arrears   cases {Enter}");

    expect(await screen.findByRole("button", { name: /^Arrears cases/, expanded: true })).toBeInTheDocument();
    expect(requests).toEqual(["POST Arrears cases"]);
    expect(announced()).toHaveTextContent("Created group Arrears cases");
    expect(screen.getByRole("button", { name: "New group" })).toHaveFocus();
  });

  it("Escape cancels a new group; a blank name is refused", async () => {
    const requests = api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await user.click(await within(conversations()).findByRole("button", { name: "New group" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Give the group a name.");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("textbox", { name: "Group name" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New group" })).toHaveFocus();
    expect(requests).toEqual([]);
  });

  it("Move to group… lists the groups and No group, moves the conversation and announces it", async () => {
    const requests = api({ groups: [{ group_id: "g1", name: "Arrears" }, { group_id: "g2", name: "Renewals" }] });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await within(conversations()).findByRole("button", { name: "Options for Arrears for Cendana" });

    await user.click(screen.getByRole("button", { name: "Options for Arrears for Cendana" }));
    await user.click(screen.getByRole("menuitem", { name: "Move to group…" }));
    const choices = screen.getByRole("menu", { name: "Move Arrears for Cendana to" });
    expect(within(choices).getAllByRole("menuitemradio").map((c) => [c.textContent, c.getAttribute("aria-checked")])).toEqual([
      ["Arrears", "false"],
      ["Renewals", "false"],
      ["No group", "true"],
    ]);
    expect(within(choices).getByRole("menuitemradio", { name: "No group" })).toHaveFocus();
    await user.keyboard("{Home}{Enter}");

    await waitFor(() => expect(titles(group("Arrears"))).toEqual(["Arrears for Cendana"]));
    expect(titles(recent())).toEqual(["What is a letter of demand?"]);
    expect(announced()).toHaveTextContent("Moved Arrears for Cendana to Arrears");
    expect(screen.getByRole("button", { name: "Options for Arrears for Cendana" })).toHaveFocus();

    await moveTo(user, "Arrears for Cendana", "No group");

    await waitFor(() => expect(titles(recent())).toEqual(["What is a letter of demand?", "Arrears for Cendana"]));
    expect(announced()).toHaveTextContent("Moved Arrears for Cendana to Recent");
    expect(requests).toEqual(["MOVE t8 g1", "MOVE t8 null"]);
  });

  it("Escape leaves Move to group… back on the Options button; a refused move is shown", async () => {
    api({ groups: [{ group_id: "g1", name: "Arrears" }], refuseMove: "Group not found" });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    const options = await within(conversations()).findByRole("button", { name: "Options for Arrears for Cendana" });

    await user.click(options);
    await user.click(screen.getByRole("menuitem", { name: "Move to group…" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(options).toHaveFocus();

    await moveTo(user, "Arrears for Cendana", "Arrears");

    expect(await screen.findByRole("alert")).toHaveTextContent("Group not found");
    expect(titles(recent())).toContain("Arrears for Cendana");
  });

  it("lists a group's conversations newest first", async () => {
    api({
      groups: [{ group_id: "g1", name: "Arrears" }],
      threads: [
        { thread_id: "t3", title: "Newest", updated_at: "2026-11-03T10:00:00Z", group_id: "g1" },
        { thread_id: "t2", title: "Loose", updated_at: "2026-11-02T10:00:00Z", group_id: null },
        { thread_id: "t1", title: "Oldest", updated_at: "2026-11-01T10:00:00Z", group_id: "g1" },
      ],
    });
    render(inShell(<p>screen</p>));

    await waitFor(() => expect(titles(group("Arrears"))).toEqual(["Newest", "Oldest"]));
    expect(titles(recent())).toEqual(["Loose"]);
  });

  it("renames a group in place, announced", async () => {
    const requests = api({ groups: [{ group_id: "g1", name: "Arrears" }] });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await user.click(await within(conversations()).findByRole("button", { name: "Options for group Arrears" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename group" }));
    const field = screen.getByRole("textbox", { name: "Group name" });
    await user.clear(field);
    await user.type(field, "Arrears 2026{Enter}");

    expect(await screen.findByRole("button", { name: /^Arrears 2026/ })).toBeInTheDocument();
    expect(requests).toEqual(["PATCH g1 Arrears 2026"]);
    expect(announced()).toHaveTextContent("Renamed group to Arrears 2026");
    expect(screen.getByRole("button", { name: "Options for group Arrears 2026" })).toHaveFocus();
  });

  it("deletes a group after confirming: its conversations go back to Recent, none is deleted", async () => {
    const requests = api({
      groups: [{ group_id: "g1", name: "Arrears" }],
      threads: [
        { thread_id: "t9", title: "What is a letter of demand?", updated_at: "2026-11-02T10:00:00Z", group_id: "g1" },
        { thread_id: "t8", title: "Arrears for Cendana", updated_at: "2026-11-01T10:00:00Z", group_id: null },
      ],
    });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await user.click(await within(conversations()).findByRole("button", { name: "Options for group Arrears" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete group" }));
    const confirm = screen.getByRole("group", { name: "Delete group Arrears?" });
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(confirm).toHaveTextContent("Its conversations go back to Recent");
    await user.click(within(confirm).getByRole("button", { name: "Delete group" }));

    await waitFor(() => expect(screen.queryByRole("list", { name: "Arrears" })).not.toBeInTheDocument());
    expect(titles(recent())).toEqual(["What is a letter of demand?", "Arrears for Cendana"]);
    expect(requests).toEqual(["DELETE group g1"]);
    expect(announced()).toHaveTextContent("Deleted group Arrears. Its conversations are back in Recent.");
    expect(screen.getByRole("heading", { name: "Groups" })).toHaveFocus();
  });

  it("collapses and expands a group, remembered in the browser", async () => {
    api({
      groups: [{ group_id: "g1", name: "Arrears" }],
      threads: [{ thread_id: "t1", title: "In a group", updated_at: "2026-11-01T10:00:00Z", group_id: "g1" }],
    });
    const user = userEvent.setup();
    const { unmount } = render(inShell(<p>screen</p>));
    const toggle = await screen.findByRole("button", { name: /^Arrears/, expanded: true });
    expect(toggle).toHaveAccessibleName("Arrears, 1 conversation");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "In a group" })).not.toBeInTheDocument();
    unmount();

    render(inShell(<p>screen</p>));
    const again = await screen.findByRole("button", { name: /^Arrears/ });
    expect(again).toHaveAttribute("aria-expanded", "false");
    await user.click(again);
    expect(screen.getByRole("button", { name: "In a group" })).toBeInTheDocument();
  });

  it("moving into a collapsed group opens it, so the moved conversation keeps focus", async () => {
    localStorage.setItem("plg_collapsed_groups", JSON.stringify(["g1"]));
    api({ groups: [{ group_id: "g1", name: "Arrears" }] });
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));

    await moveTo(user, "Arrears for Cendana", "Arrears");

    await waitFor(() => expect(screen.getByRole("button", { name: "Options for Arrears for Cendana" })).toHaveFocus());
    expect(screen.getByRole("button", { name: /^Arrears,/ })).toHaveAttribute("aria-expanded", "true");
  });
});
