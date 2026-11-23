import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import type { UserCtx } from "@/lib/events";
import { server } from "@/test/msw";
import { fixture, sseResponse } from "@/test/sse";

// Personas from PLG Records' staff table, one per role the prompts are filtered on.
const OFFICER: UserCtx = {
  staff_id: "S05",
  name: "Siti Aishah Yusof",
  title: "Leasing Officer",
  dept: "Estate Management",
  role: "officer",
  developer: false,
};
const ANALYST: UserCtx = { ...OFFICER, staff_id: "S08", name: "Kelvin Goh", title: "Data Analyst, Ops Analytics", role: "analyst" };
const LEGAL: UserCtx = { ...OFFICER, staff_id: "S09", name: "Joanne Teo", title: "Legal Counsel", role: "legal" };

/** The starter prompts' labels, in order. */
function prompts(): string[] {
  const list = screen.getByRole("list", { name: "Starter prompts" });
  return within(list)
    .getAllByRole("button")
    .map((b) => b.textContent ?? "");
}

beforeEach(() => {
  sessionStorage.clear();
  server.use(
    http.get("/api/threads/:id/runs/latest", () => HttpResponse.json({ detail: "No run to resume" }, { status: 404 })),
  );
});

describe("Welcome screen", () => {
  it("greets the officer by name in a new conversation and offers what the Super-Librarian can do", () => {
    render(<AskScreen user={OFFICER} />);

    expect(screen.getByRole("heading", { name: "Good to see you, Siti Aishah Yusof" })).toBeInTheDocument();
    expect(prompts()).toEqual([
      expect.stringContaining("policy"),
      expect.stringContaining("PLG Records"),
      expect.stringContaining("Draft a letter"),
      expect.stringContaining("Classify feedback"),
      expect.stringContaining("Check an application"),
      expect.stringContaining("My top tasks"),
    ]);
  });

  it("offers analysts no letters, tickets or notices to send", () => {
    render(<AskScreen user={ANALYST} />);

    const offered = prompts();
    expect(offered.length).toBeGreaterThanOrEqual(4);
    expect(offered).not.toContainEqual(expect.stringContaining("Draft a letter"));
    expect(offered).not.toContainEqual(expect.stringContaining("Classify feedback"));
    expect(offered).not.toContainEqual(expect.stringContaining("Check an application"));
    expect(offered).toContainEqual(expect.stringContaining("PLG Records"));
  });

  it("offers legal letters but no defect tickets", () => {
    render(<AskScreen user={LEGAL} />);

    const offered = prompts();
    expect(offered).toContainEqual(expect.stringContaining("Draft a letter"));
    expect(offered).not.toContainEqual(expect.stringContaining("Classify feedback"));
  });

  it("asks a chosen prompt at once and streams its answer; the welcome gives way to the conversation", async () => {
    let asked = "";
    server.use(
      http.post("/api/threads", () => HttpResponse.json({ thread_id: "t1" }, { status: 201 })),
      http.post("/api/threads/:id/runs", async ({ request }) => {
        asked = ((await request.json()) as { message: string }).message;
        return sseResponse(fixture("tasks"));
      }),
    );
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);

    // By keyboard: focus the prompt and press Enter.
    const tasks = within(screen.getByRole("list", { name: "Starter prompts" })).getByRole("button", {
      name: /My top tasks/,
    });
    tasks.focus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled(), { timeout: 5000 });
    expect(asked).toBe("What are my top 5 tasks this week and why?");
    expect(screen.getByText("What are my top 5 tasks this week and why?", { selector: "[data-bubble]" })).toBeVisible();
    expect(within(screen.getByRole("region", { name: "Answer" })).getByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Starter prompts" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Good to see you/ })).not.toBeInTheDocument();
  });

  it("asks a clicked prompt", async () => {
    let asked = "";
    server.use(
      http.post("/api/threads", () => HttpResponse.json({ thread_id: "t1" }, { status: 201 })),
      http.post("/api/threads/:id/runs", async ({ request }) => {
        asked = ((await request.json()) as { message: string }).message;
        return sseResponse(fixture("answer"));
      }),
    );
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);

    await user.click(screen.getByRole("button", { name: /Ask about a policy/ }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled(), { timeout: 5000 });
    expect(asked).toBe("How far can a tenant display goods beyond the shopfront?");
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("POL-003 v2.0");
  });

  it("is not shown for a conversation that already has turns", async () => {
    sessionStorage.setItem("plg_active_thread", "t1");
    server.use(
      http.get("/api/threads/:id", () =>
        HttpResponse.json({
          thread_id: "t1",
          title: "Arrears",
          messages: [
            { role: "user", content: "When do we issue a letter of demand?" },
            { role: "assistant", content: "At 60 days." },
          ],
          turns: [],
          pending: [],
          running: null,
        }),
      ),
    );
    render(<AskScreen user={OFFICER} />);

    expect(await screen.findByRole("list", { name: "Earlier in this conversation" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Starter prompts" })).not.toBeInTheDocument();
  });
});
