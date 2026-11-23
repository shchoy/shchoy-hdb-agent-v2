import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import { server } from "@/test/msw";
import { inShell, OFFICER } from "@/test/shell";
import { approvalsFixture, fixture, sseResponse } from "@/test/sse";

const navigation = vi.hoisted(() => ({ pathname: "/", push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push, refresh: navigation.refresh }),
}));

const PENDING = approvalsFixture("pending.json");
const THREADS = [
  { thread_id: "t9", title: "What is a letter of demand?", updated_at: "2026-11-02T10:00:00Z" },
  { thread_id: "t8", title: "Arrears for Cendana", updated_at: "2026-11-01T10:00:00Z" },
];

function api({ approvals = [] as unknown[], threads = THREADS } = {}) {
  server.use(
    http.get("/api/threads", () => HttpResponse.json(threads)),
    http.get("/api/approvals", () => HttpResponse.json(approvals)),
  );
}

function sidebarNav() {
  return screen.getByRole("navigation", { name: "Main" });
}

beforeEach(() => {
  sessionStorage.clear();
  navigation.pathname = "/";
  navigation.push.mockReset();
});

describe("App shell", () => {
  it("lists every section, marking the current one", () => {
    api();
    navigation.pathname = "/tasks";
    render(inShell(<p>Tasks screen</p>));

    const links = within(sidebarNav()).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Ask",
      "Approvals",
      "Tasks",
      "Document check",
      "Library",
      "Memory",
    ]);
    expect(within(sidebarNav()).getByRole("link", { name: "Tasks" })).toHaveAttribute("aria-current", "page");
    expect(within(sidebarNav()).getByRole("link", { name: "Ask" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("main")).toHaveTextContent("Tasks screen");
  });

  it("shows the signed-in persona with sign-out", () => {
    api();
    render(inShell(<p>screen</p>));

    expect(screen.getByText(/Signed in as/)).toHaveTextContent(`Signed in as ${OFFICER.name}`);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("counts the approvals waiting for the officer, as many as the inbox lists", async () => {
    api({ approvals: PENDING });
    render(inShell(<p>screen</p>));

    const link = within(sidebarNav()).getByRole("link", { name: /^Approvals/ });
    await waitFor(() => expect(link).toHaveAccessibleName(`Approvals, ${PENDING.length} pending`));
  });

  it("shows no count when nothing is waiting", async () => {
    let asked = 0;
    server.use(
      http.get("/api/threads", () => HttpResponse.json([])),
      http.get("/api/approvals", () => {
        asked++;
        return HttpResponse.json([]);
      }),
    );
    render(inShell(<p>screen</p>));

    await waitFor(() => expect(asked).toBe(1));
    expect(within(sidebarNav()).getByRole("link", { name: "Approvals" })).toHaveAccessibleName("Approvals");
  });

  it("counts an action an answer proposed once the answer is done", async () => {
    let approvals: unknown[] = [];
    server.use(
      http.get("/api/threads", () => HttpResponse.json([])),
      http.get("/api/approvals", () => HttpResponse.json(approvals)),
      http.post("/api/threads", () => HttpResponse.json({ thread_id: "t1" }, { status: 201 })),
      http.post("/api/threads/:id/runs", () => {
        approvals = PENDING.slice(0, 1);
        return sseResponse(fixture("draft"));
      }),
    );
    const user = userEvent.setup();
    render(inShell(<AskScreen />));

    await user.type(screen.getByLabelText("Your question"), "Draft a reminder");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(
      () =>
        expect(within(sidebarNav()).getByRole("link", { name: /^Approvals/ })).toHaveAccessibleName(
          "Approvals, 1 pending",
        ),
      { timeout: 5000 },
    );
  }, 10_000);

  it("lists recent conversations; picking one elsewhere opens it on the Ask screen", async () => {
    api();
    navigation.pathname = "/library";
    const user = userEvent.setup();
    render(inShell(<p>Library screen</p>));

    const conversations = screen.getByRole("navigation", { name: "Conversations" });
    await user.click(await within(conversations).findByRole("button", { name: "Arrears for Cendana" }));

    expect(sessionStorage.getItem("plg_active_thread")).toBe("t8");
    expect(navigation.push).toHaveBeenCalledWith("/");
  });

  it("starts a new conversation on the Ask screen from elsewhere", async () => {
    api();
    sessionStorage.setItem("plg_active_thread", "t9");
    navigation.pathname = "/memory";
    const user = userEvent.setup();
    render(inShell(<p>Memory screen</p>));

    await user.click(screen.getByRole("button", { name: "New conversation" }));

    expect(sessionStorage.getItem("plg_active_thread")).toBeNull();
    expect(navigation.push).toHaveBeenCalledWith("/");
  });

  it("marks the conversation open on the Ask screen", async () => {
    api();
    server.use(
      http.get("/api/threads/t9", () =>
        HttpResponse.json({ thread_id: "t9", title: THREADS[0].title, messages: [], summary: "", running: null }),
      ),
    );
    const user = userEvent.setup();
    render(inShell(<AskScreen />));

    const conversations = screen.getByRole("navigation", { name: "Conversations" });
    const picked = await within(conversations).findByRole("button", { name: THREADS[0].title });
    await user.click(picked);

    await waitFor(() => expect(picked).toHaveAttribute("aria-current", "true"));
    expect(navigation.push).not.toHaveBeenCalled();
  });
});

describe("Drawer", () => {
  it("opens from a labelled button, moves focus into it, and closes on Escape back to the button", async () => {
    api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");

    await user.click(menu);

    const drawer = screen.getByRole("dialog", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
  });

  it("keeps Tab inside the open drawer", async () => {
    api({ threads: [] });
    const user = userEvent.setup();
    render(inShell(<button type="button">On the screen</button>));
    await user.click(screen.getByRole("button", { name: "Menu" }));
    const drawer = screen.getByRole("dialog", { name: "Menu" });

    for (let i = 0; i < 12; i++) {
      await user.tab();
      expect(drawer).toContainElement(document.activeElement as HTMLElement);
    }
    await user.tab({ shift: true });
    expect(drawer).toContainElement(document.activeElement as HTMLElement);
  });

  it("closes once a section is picked", async () => {
    api();
    const user = userEvent.setup();
    render(inShell(<p>screen</p>));
    await user.click(screen.getByRole("button", { name: "Menu" }));

    await user.click(within(screen.getByRole("dialog", { name: "Menu" })).getByRole("link", { name: "Library" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
