import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import type { UserCtx } from "@/lib/events";
import { server } from "@/test/msw";
import { inShell, OFFICER } from "@/test/shell";
import { approvalsFixture, fixture, sseResponse } from "@/test/sse";

// The chat's "Awaiting approval" card: the Approvals inbox's cards (recorded approvals fixtures), in the conversation.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

type Pending = { action_id: string; thread_id: string; title: string; thread_title: string; [key: string]: unknown };
const [FEEDBACK, REMINDER, TICKET] = approvalsFixture("pending.json") as Pending[];
const [GLOSSARY] = approvalsFixture("glossary_pending.json") as Pending[];
const ANALYST: UserCtx = { ...OFFICER, staff_id: "S08", name: "Kelvin Goh", title: "Data Analyst", role: "analyst" };
const PROPOSER: UserCtx = { ...OFFICER, staff_id: "S02", name: "Proposer", role: "manager" };

/** How plg-api holds a pending action in its thread: a ProposedAction, without the inbox's thread fields. */
function inThread(action: Pending) {
  return Object.fromEntries(Object.entries(action).filter(([field]) => field !== "thread_id" && field !== "thread_title"));
}

/** A reopened conversation (after a reload) whose last answer proposed `pending`. */
function reopened(action: Pending) {
  const thread = action.thread_id;
  sessionStorage.setItem("plg_active_thread", thread);
  let pending = [inThread(action)];
  server.use(
    http.get(`/api/threads/${thread}`, () =>
      HttpResponse.json({
        thread_id: thread,
        title: action.thread_title,
        messages: [
          { role: "user", content: action.thread_title },
          { role: "assistant", content: "I drafted it. It waits for your approval." },
        ],
        summary: "",
        pending,
        turns: [],
      }),
    ),
    http.get("/api/approvals", () => HttpResponse.json(pending.length === 0 ? [] : [action])),
  );
  return {
    /** plg-api resumes the thread with the recorded stream; the action is no longer pending. */
    resumes(stream: string) {
      const sent: unknown[] = [];
      server.use(
        http.post(`/api/threads/${thread}/resume`, async ({ request }) => {
          sent.push(await request.json());
          pending = [];
          return sseResponse(stream);
        }),
      );
      return sent;
    },
  };
}

const awaiting = (title: string) => screen.findByRole("region", { name: title });

beforeEach(() => {
  sessionStorage.clear();
  server.use(
    http.get("/api/threads", () => HttpResponse.json([])),
    http.get("/api/approvals", () => HttpResponse.json([])),
    http.get("/api/threads/:id/runs/latest", () => HttpResponse.json({ detail: "No run to resume" }, { status: 404 })),
  );
});

describe("Approval card in the chat", () => {
  it("shows the action a run proposed as an Awaiting approval card in that answer, with its preview", async () => {
    server.use(
      http.post("/api/threads", () => HttpResponse.json({ thread_id: "t1" }, { status: 201 })),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("draft"))),
    );
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);
    await user.type(screen.getByLabelText("Your question"), "Draft an update reply for FB-2025-00002");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    const answer = await screen.findByRole("region", { name: "Answer" });
    const card = await within(answer).findByRole(
      "region",
      { name: "Send Feedback Update Reply to Sir/Madam" },
      { timeout: 5000 }, // the whole recorded run replays first
    );
    expect(within(card).getByText("Awaiting approval")).toBeInTheDocument();
    expect(card).toHaveTextContent("Feedback Update Reply (TPL-FBK-03 v1.3)");
    expect(card).not.toHaveTextContent("From the conversation");
    expect(within(card).getByTitle("Letter to send: Send Feedback Update Reply to Sir/Madam")).toHaveAttribute("sandbox", "");
    // An open slot: the letter can't be approved as it is, only edited (filled) or rejected.
    expect(within(card).queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Edit slots" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Reject…" })).toBeEnabled();
  });

  it("shows the pending action again after a reload, and sends the edited letter from the card", async () => {
    const api = reopened(FEEDBACK);
    const sent = api.resumes(approvalsFixture("edit.sse"));
    const user = userEvent.setup();
    render(inShell(<AskScreen user={OFFICER} />));

    const card = await awaiting(FEEDBACK.title);
    expect(await screen.findByRole("link", { name: "Approvals, 1 pending" })).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Edit slots" }));
    await user.type(within(card).getByLabelText("action_taken"), "Our contractor sealed the ceiling joint.");
    await user.click(within(card).getByRole("button", { name: "Send edited letter" }));

    await waitFor(() =>
      expect(card).toHaveTextContent(
        `${FEEDBACK.title}: sent with your edits as ${FEEDBACK.action_id}-v2 (version 2).`,
      ),
    );
    expect(within(card).getByText("Sent")).toBeInTheDocument();
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
    expect(sent).toEqual([
      {
        action_id: FEEDBACK.action_id,
        version: 1,
        decision: "edit",
        edits: { action_taken: "Our contractor sealed the ceiling joint." },
      },
    ]);
    // The sidebar's count is read again: the action left the Approvals inbox.
    expect(await screen.findByRole("link", { name: "Approvals" })).toBeInTheDocument();
  });

  it("rejects with a reason from the card and says nothing was sent", async () => {
    const api = reopened(REMINDER);
    const sent = api.resumes(approvalsFixture("reject.sse"));
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);

    const card = await awaiting(REMINDER.title);
    await user.click(within(card).getByRole("button", { name: "Reject…" }));
    await user.type(within(card).getByLabelText("Reason for rejecting"), "The tenant paid yesterday.");
    await user.click(within(card).getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(card).toHaveTextContent(`${REMINDER.title}: rejected; nothing was sent.`));
    expect(within(card).getByText("Rejected")).toBeInTheDocument();
    expect(sent).toEqual([
      { action_id: REMINDER.action_id, version: 1, decision: "reject", reason: "The tenant paid yesterday." },
    ]);
  });

  it("raises an i-EMS ticket from the card with the ticket ID it got", async () => {
    const api = reopened(TICKET);
    api.resumes(approvalsFixture("ticket_edit.sse"));
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);

    const card = await awaiting(TICKET.title);
    await user.click(within(card).getByRole("button", { name: "Edit ticket" }));
    await user.selectOptions(within(card).getByLabelText("Category"), "SEP");
    await user.click(within(card).getByRole("button", { name: "Raise edited ticket" }));

    await waitFor(() => expect(card).toHaveTextContent(/raised with your edits as IEMS-\S+ \(version 2\)/));
  });

  it("shows clearly why plg-api refused the decision, and keeps the controls", async () => {
    reopened(REMINDER);
    server.use(
      http.post(`/api/threads/${REMINDER.thread_id}/resume`, () =>
        HttpResponse.json({ detail: "That version of the action is not pending" }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);

    const card = await awaiting(REMINDER.title);
    await user.click(within(card).getByRole("button", { name: "Approve and send" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("That version of the action is not pending");
    expect(within(card).getByText("Awaiting approval")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Approve and send" })).toBeEnabled();
  });

  it("shows plg-api's refusal when the role may not approve", async () => {
    reopened(REMINDER);
    server.use(
      http.post(`/api/threads/${REMINDER.thread_id}/resume`, () =>
        HttpResponse.json({ detail: "Your role can't approve this action" }, { status: 403 }),
      ),
    );
    const user = userEvent.setup();
    render(<AskScreen user={OFFICER} />);

    const card = await awaiting(REMINDER.title);
    await user.click(within(card).getByRole("button", { name: "Approve and send" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("Your role can't approve this action");
  });

  it("gives a role that can't send no approve or edit controls, and says who it was sent to", async () => {
    reopened(REMINDER);
    render(<AskScreen user={ANALYST} />);

    const card = await awaiting(REMINDER.title);
    expect(within(card).getByText("Awaiting approval")).toBeInTheDocument();
    expect(card).toHaveTextContent("Sent to approvers: Officer, estate manager, manager, director, legal.");
    expect(within(card).queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Edit slots" })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Reject…" })).toBeEnabled();
  });

  it("lets the proposer of a glossary change only withdraw it: the term owner approves", async () => {
    reopened(GLOSSARY);
    render(<AskScreen user={PROPOSER} />);

    const card = await awaiting(GLOSSARY.title);
    expect(card).toHaveTextContent("Sent to approvers: Kelvin Goh (term owner).");
    expect(within(card).queryByRole("button", { name: "Approve change" })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Edit change" })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Withdraw…" })).toBeEnabled();
  });
});
