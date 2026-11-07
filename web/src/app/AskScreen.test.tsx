import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import { server } from "@/test/msw";
import { documentFixture } from "@/test/documents";
import { fixture, sseResponse } from "@/test/sse";

const QUESTION = "When do we issue a letter of demand?";

function threadsApi() {
  return http.post("/api/threads", () =>
    HttpResponse.json({ thread_id: "t1" }, { status: 201 }),
  );
}

async function ask(question = QUESTION) {
  const user = userEvent.setup();
  render(<AskScreen />);
  await user.type(screen.getByLabelText("Your question"), question);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return user;
}

/**
 * Waits until the run is over: Ask is enabled again. A whole replayed run (plus, for the file's first test,
 * the cold start) can outlast waitFor's 1s default on a slow CI runner, so allow longer.
 */
async function runFinished() {
  await waitFor(
    () => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled(),
    { timeout: 5000 },
  );
}

const NO_THREADS = http.get("/api/threads", () => HttpResponse.json([]));
const NO_RUN_TO_RESUME = http.get("/api/threads/:id/runs/latest", () =>
  HttpResponse.json({ detail: "No run to resume" }, { status: 404 }),
);

beforeEach(() => {
  sessionStorage.clear();
  server.use(NO_THREADS, NO_RUN_TO_RESUME);
});

describe("Ask screen", () => {
  it("streams the answer and shows the trajectory finished", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("answer"))),
    );

    await ask();
    await runFinished();

    const answer = screen.getByRole("region", { name: "Answer" });
    expect(within(answer).getByText("POL-003 v2.0").tagName).toBe("STRONG");
    expect(answer).toHaveTextContent(
      "Under POL-003 v2.0, a letter of demand is issued once arrears reach 60 days [1].",
    );
    const trajectory = screen.getByRole("list", { name: "Trajectory" });
    expect(
      within(trajectory)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "load_memory ✓ finished",
      "route ✓ finished",
      "knowledge ✓ finished",
      "merge ✓ finished",
      "write_memory ✓ finished",
    ]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a citation chip for each cited source, with the quoted span", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("answer"))),
    );

    const user = await ask();
    await runFinished();

    const sources = screen.getByRole("list", { name: "Sources" });
    const [chip] = within(sources).getAllByRole("listitem");
    expect(chip).toHaveTextContent("[1]");
    expect(chip).toHaveTextContent(
      "PLG-POL-003 Rental Arrears Management Policy (v2.0)",
    );
    expect(chip).toHaveTextContent(
      "4. Policy Statements > 4.5 Letter of Demand",
    );
    const quote = within(chip).getByText(/when any amount is 60 days overdue/);
    expect(quote).not.toBeVisible();
    await user.click(within(chip).getByText("[1]"));
    expect(quote).toBeVisible();
  });

  it("opens a cited source with its span highlighted", async () => {
    const recorded = documentFixture("docx");
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("answer"))),
      http.get("/api/documents/:id", () =>
        HttpResponse.json(recorded.document),
      ),
      http.get("/api/documents/:id/chunks/:chunk", () =>
        HttpResponse.json(recorded.location),
      ),
    );

    const user = await ask();
    await runFinished();
    await user.click(screen.getByText("[1]"));
    await user.click(screen.getByRole("button", { name: "Open source" }));

    const viewer = await screen.findByRole("region", {
      name: `Source: ${recorded.document.title}`,
    });
    expect(viewer.querySelector("mark")).toBeInTheDocument();
  });

  it("says the sources don't cover the question, with no citation chips", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        sseResponse(fixture("not_covered")),
      ),
    );

    await ask();
    await runFinished();

    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent(
      "The indexed PLG sources don't cover this question",
    );
    expect(
      screen.queryByRole("list", { name: "Sources" }),
    ).not.toBeInTheDocument();
  });

  it("sends the question to the run on a new thread", async () => {
    const requests: { thread: string; body: unknown }[] = [];
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", async ({ params, request }) => {
        requests.push({
          thread: String(params.id),
          body: await request.json(),
        });
        return sseResponse(fixture("answer"));
      }),
    );

    await ask();

    await screen.findByText(/arrears reach 60 days/);
    expect(requests).toEqual([{ thread: "t1", body: { message: QUESTION } }]);
  });

  it("reuses the thread for a follow-up question", async () => {
    let threadsCreated = 0;
    const threads: string[] = [];
    server.use(
      http.post("/api/threads", () => {
        threadsCreated += 1;
        return HttpResponse.json(
          { thread_id: `t${threadsCreated}` },
          { status: 201 },
        );
      }),
      http.post("/api/threads/:id/runs", ({ params }) => {
        threads.push(String(params.id));
        return sseResponse(fixture("answer"));
      }),
    );

    const user = await ask();
    await runFinished();
    await user.type(screen.getByLabelText("Your question"), "And after that?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await runFinished();

    expect(threadsCreated).toBe(1);
    expect(threads).toEqual(["t1", "t1"]);
  });

  it("warns that the answer is incomplete on an error event and Retry re-asks", async () => {
    const asked: unknown[] = [];
    let call = 0;
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", async ({ request }) => {
        asked.push(await request.json());
        call += 1;
        return sseResponse(fixture(call === 1 ? "error" : "answer"));
      }),
    );

    const user = await ask();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/incomplete and must not be trusted/);
    expect(screen.queryByText(/a letter of$/)).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(
      await screen.findByText(/arrears reach 60 days/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(asked).toEqual([{ message: QUESTION }, { message: QUESTION }]);
  });

  it("shows the error alert when a frame is malformed", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        sseResponse(
          'id: 1\r\nevent: token\r\ndata: {"type":"token","seq":"x"}\r\n\r\n',
        ),
      ),
    );

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /incomplete and must not be trusted/,
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows the error alert when the stream ends without finishing", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        sseResponse(fixture("answer").split("event: done")[0]),
      ),
    );

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /incomplete and must not be trusted/,
    );
  });

  it("shows the error alert when the run request fails", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        HttpResponse.json({ detail: "boom" }, { status: 502 }),
      ),
    );

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /incomplete and must not be trusted/,
    );
  });

  it("shows the error alert when the network is down", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => HttpResponse.error()),
    );

    await ask();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("disables Ask while the answer is streaming", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("answer"))),
    );

    await ask();

    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await runFinished();
    expect(screen.getByText(/arrears reach 60 days/)).toBeInTheDocument();
  });

  it("shows the draft preview with open slots and personal-data flags, and a DOCX download", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("draft"))),
    );

    await ask(
      "Draft an update reply to the member of public who gave feedback FB-2025-00002",
    );
    await runFinished();

    const preview = screen.getByRole("region", { name: "Draft preview" });
    expect(preview).toHaveTextContent(
      "Feedback Update Reply (TPL-FBK-03 v1.3). Nothing has been sent.",
    );
    const frame = within(preview).getByTitle(
      "Preview of Feedback Update Reply",
    );
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain("a leaking ceiling");
    const unfilled = within(preview).getByRole("list", {
      name: "Unfilled slots",
    });
    expect(
      within(unfilled)
        .getAllByRole("listitem")
        .map((li) => li.querySelector("code")?.textContent),
    ).toEqual(["action_taken"]);
    const flags = within(preview).getByRole("list", {
      name: "Personal data flags",
    });
    expect(flags).toHaveTextContent("next_steps");
    expect(
      within(preview).getByRole("link", { name: "Download DOCX" }),
    ).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/api\/drafts\/[0-9a-f-]+\/file$/),
    );
  });

  it("shows the policy stance card in the Sources panel with scope, dates and superseded versions", async () => {
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () =>
        sseResponse(fixture("policy_stance")),
      ),
    );

    await ask("How far can a tenant display goods beyond the shopfront?");
    await runFinished();

    const sources = screen.getByRole("heading", { name: "Sources" })
      .parentElement as HTMLElement;
    const pol001 = within(sources).getByRole("region", { name: /PLG-POL-001/ });
    const overrides = within(pol001).getByRole("list", {
      name: "Overriding circulars",
    });
    expect(overrides).toHaveTextContent(
      "Circular 07/2026 overrides clause 7.3",
    );
    expect(overrides).toHaveTextContent("1 Aug 2026");
    expect(within(overrides).getByText("NC units only")).toBeInTheDocument();
    expect(overrides).toHaveTextContent(
      "replaces the 0.6 m limit in clause 7.3",
    );

    const pol003 = within(sources).getByRole("region", { name: /PLG-POL-003/ });
    expect(pol003).toHaveTextContent("In force: version 2.0, from 1 Apr 2026");
    const superseded = within(pol003).getByRole("list", {
      name: "Superseded versions",
    });
    expect(superseded).toHaveTextContent(
      "Version 1.0 (superseded, ended 31 Mar 2026)",
    );
    expect(superseded).toHaveTextContent("Supersedes | v1.0 (1 Mar 2024)");
  });
});

describe("Conversations", () => {
  const PAST = {
    thread_id: "t9",
    title: "What is a letter of demand?",
    messages: [
      { role: "user", content: "What is a letter of demand?" },
      { role: "assistant", content: "A formal demand for payment of arrears." },
    ],
    summary: "",
    running: null,
  };

  it("lists past conversations and reopens one with its history, then continues it in the same thread", async () => {
    const asked: string[] = [];
    server.use(
      http.get("/api/threads", () =>
        HttpResponse.json([
          {
            thread_id: "t9",
            title: PAST.title,
            updated_at: "2026-11-02T10:00:00Z",
          },
        ]),
      ),
      http.get("/api/threads/t9", () => HttpResponse.json(PAST)),
      http.post("/api/threads/:id/runs", ({ params }) => {
        asked.push(String(params.id));
        return sseResponse(fixture("answer"));
      }),
    );
    const user = userEvent.setup();
    render(<AskScreen />);

    await user.click(await screen.findByRole("button", { name: PAST.title }));

    const history = await screen.findByRole("list", {
      name: "Earlier in this conversation",
    });
    expect(history).toHaveTextContent(
      "A formal demand for payment of arrears.",
    );
    await user.type(screen.getByLabelText("Your question"), "and for Cendana?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await runFinished();
    expect(asked).toEqual(["t9"]);
  });

  it("starts a fresh conversation", async () => {
    server.use(
      http.get("/api/threads", () =>
        HttpResponse.json([
          { thread_id: "t9", title: PAST.title, updated_at: "x" },
        ]),
      ),
      http.get("/api/threads/t9", () => HttpResponse.json(PAST)),
    );
    const user = userEvent.setup();
    render(<AskScreen />);
    await user.click(await screen.findByRole("button", { name: PAST.title }));
    await screen.findByRole("list", { name: "Earlier in this conversation" });

    await user.click(screen.getByRole("button", { name: "New conversation" }));

    expect(
      screen.queryByRole("list", { name: "Earlier in this conversation" }),
    ).not.toBeInTheDocument();
  });

  it("reconnects after the connection drops, from the last event it saw", async () => {
    const [head, tail] = fixture("answer").split("id: 23");
    const lastSeen = [...head.matchAll(/^id: (\d+)/gm)].at(-1)?.[1];
    const resumedFrom: (string | null)[] = [];
    server.use(
      threadsApi(),
      http.post("/api/threads/:id/runs", () => sseResponse(head)),
      http.get("/api/threads/:id/runs/latest", ({ request }) => {
        resumedFrom.push(request.headers.get("last-event-id"));
        return sseResponse("id: 23" + tail);
      }),
    );

    await ask();
    await runFinished();

    expect(resumedFrom).toEqual([lastSeen]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent(
      "arrears reach 60 days [1]",
    );
  });

  it("after a refresh, picks up the answer still being written", async () => {
    sessionStorage.setItem("plg_active_thread", "t9");
    server.use(
      http.get("/api/threads/t9", () =>
        HttpResponse.json({ ...PAST, messages: [], running: QUESTION }),
      ),
      http.get("/api/threads/t9/runs/latest", () =>
        sseResponse(fixture("answer")),
      ),
    );

    render(<AskScreen />);

    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent(
        "arrears reach 60 days [1]",
      ),
    );
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
  });
});
