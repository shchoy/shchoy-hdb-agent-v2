import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApprovalsScreen } from "@/app/approvals/ApprovalsScreen";
import { server } from "@/test/msw";
import { approvalsFixture, sseResponse } from "@/test/sse";

// Recorded from plg-api (scripts/record_sse_fixtures.py): a feedback reply with an open slot and a phone number
// flagged, and a complete arrears reminder, proposed in two conversations; then the reply edited, the reminder rejected.
const PENDING = approvalsFixture("pending.json");
const AUDIT = approvalsFixture("audit.json");
const [FEEDBACK, REMINDER] = PENDING as { action_id: string; thread_id: string; title: string }[];
const [REJECTED, EDITED] = AUDIT;

type Decided = { pending: unknown[]; audit: unknown[] };

/** plg-api through the BFF: resuming `thread` replays the recorded stream, after which the lists read `after`. */
function decisions(thread: string, stream: string, after: Decided) {
  const sent: unknown[] = [];
  let state: Decided = { pending: PENDING, audit: [] };
  server.use(
    http.get("/api/approvals", () => HttpResponse.json(state.pending)),
    http.get("/api/audit", () => HttpResponse.json(state.audit)),
    http.post(`/api/threads/${thread}/resume`, async ({ request }) => {
      sent.push(await request.json());
      state = after;
      return sseResponse(stream);
    }),
  );
  return sent;
}

function plgApi(pending: unknown[] = PENDING, audit: unknown[] = []) {
  server.use(
    http.get("/api/approvals", () => HttpResponse.json(pending)),
    http.get("/api/audit", () => HttpResponse.json(audit)),
  );
}

const card = (title: string) => screen.getByRole("article", { name: title });

describe("Approvals inbox", () => {
  it("lists pending actions across conversations with a preview of what would be sent", async () => {
    plgApi();
    render(<ApprovalsScreen role="officer" />);

    const pending = await screen.findByRole("list", { name: "Pending approvals" });
    expect(within(pending).getAllByRole("article")).toHaveLength(2);

    const reply = card(FEEDBACK.title);
    expect(reply).toHaveTextContent("Feedback Update Reply (TPL-FBK-03 v1.3)");
    expect(reply).toHaveTextContent("To: Sir/Madam");
    expect(reply).toHaveTextContent("Draft an update reply to the member of public who gave feedback FB-2025-00002");
    expect(within(reply).getByTitle("Letter to send: " + FEEDBACK.title)).toHaveAttribute("sandbox", "");
    expect(within(reply).getByRole("list", { name: "Unfilled slots" })).toHaveTextContent("action_taken");
    expect(within(reply).getByRole("alert")).toHaveTextContent("next_steps");
    expect(within(reply).getByRole("row", { name: /ticket_reference/ })).toHaveTextContent("IEMS-2510-0002");

    expect(card(REMINDER.title)).toHaveTextContent("To: Golden Leaf Minimart Pte Ltd");
  });

  it("says when nothing is waiting", async () => {
    plgApi([]);
    render(<ApprovalsScreen role="officer" />);

    expect(await screen.findByText("Nothing is waiting for your approval.")).toBeInTheDocument();
  });

  it("sends an edited letter, showing each change as a diff, then the result and the audit trail", async () => {
    const sent = decisions(FEEDBACK.thread_id, approvalsFixture("edit.sse"), { pending: [REMINDER], audit: [EDITED] });
    render(<ApprovalsScreen role="officer" />);

    const reply = await screen.findByRole("article", { name: FEEDBACK.title });
    await userEvent.click(within(reply).getByRole("button", { name: "Edit slots" }));
    await userEvent.type(within(reply).getByLabelText("action_taken"), "Our contractor sealed the ceiling joint on 5 October 2025.");
    const nextSteps = within(reply).getByLabelText("next_steps");
    await userEvent.clear(nextSteps);
    await userEvent.type(nextSteps, "If it recurs, please call us on 6100 2058.");

    const changed = within(reply).getByRole("row", { name: /next_steps/ });
    expect(changed.querySelector("del")).toHaveTextContent("If it recurs, call the shop on +65 9138 9404.");
    expect(changed.querySelector("ins")).toHaveTextContent("If it recurs, please call us on 6100 2058.");
    expect(within(reply).queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();

    await userEvent.click(within(reply).getByRole("button", { name: "Send edited letter" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent(`${FEEDBACK.title}: sent with your edits as ${FEEDBACK.action_id}-v2 (version 2)`);
    expect(sent).toEqual([{
      action_id: FEEDBACK.action_id, version: 1, decision: "edit",
      edits: {
        action_taken: "Our contractor sealed the ceiling joint on 5 October 2025.",
        next_steps: "If it recurs, please call us on 6100 2058.",
      },
    }]);
    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Pending approvals" })).getAllByRole("article")).toHaveLength(1),
    );

    const trail = within(await screen.findByRole("list", { name: "Audit trail" })).getByRole("article");
    expect(trail).toHaveTextContent(FEEDBACK.title);
    expect(trail).toHaveTextContent("Sent with edits by S05 (officer)");
    expect(trail).toHaveTextContent("action_taken: Our contractor sealed the ceiling joint on 5 October 2025.");
    expect(trail).toHaveTextContent(`Outbox item ${FEEDBACK.action_id}-v2 (version 2) to Sir/Madam`);
    expect(trail).toHaveTextContent(`Trace ${(EDITED as { run_id: string }).run_id}`);
  });

  it("rejects with a reason and records it in the audit trail; nothing is sent", async () => {
    const sent = decisions(REMINDER.thread_id, approvalsFixture("reject.sse"), { pending: [FEEDBACK], audit: [REJECTED] });
    render(<ApprovalsScreen role="officer" />);

    const letter = await screen.findByRole("article", { name: REMINDER.title });
    await userEvent.click(within(letter).getByRole("button", { name: "Reject…" }));
    const reject = within(letter).getByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    await userEvent.type(within(letter).getByLabelText("Reason for rejecting"), "The tenant paid yesterday.");
    await userEvent.click(reject);

    expect(await screen.findByRole("status")).toHaveTextContent(`${REMINDER.title}: rejected; nothing was sent.`);
    expect(sent).toEqual([
      { action_id: REMINDER.action_id, version: 1, decision: "reject", reason: "The tenant paid yesterday." },
    ]);
    const trail = within(await screen.findByRole("list", { name: "Audit trail" })).getByRole("article");
    expect(trail).toHaveTextContent("Rejected by S05 (officer)");
    expect(trail).toHaveTextContent("Reason: The tenant paid yesterday.");
    expect(trail).toHaveTextContent("Nothing was sent.");
  });

  it("offers Approve only for a complete letter and a role that can send it", async () => {
    plgApi();
    const { unmount } = render(<ApprovalsScreen role="officer" />);

    const reply = await screen.findByRole("article", { name: FEEDBACK.title });
    expect(within(reply).queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();
    expect(reply).toHaveTextContent("Fill the open slots (Edit slots) before the letter can be sent.");
    expect(within(card(REMINDER.title)).getByRole("button", { name: "Approve and send" })).toBeEnabled();
    unmount();

    render(<ApprovalsScreen role="analyst" />);
    const letter = await screen.findByRole("article", { name: REMINDER.title });
    expect(within(letter).queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();
    expect(within(letter).queryByRole("button", { name: "Edit slots" })).not.toBeInTheDocument();
    expect(letter).toHaveTextContent("Your role can't send this letter. You can reject it with a reason.");
    expect(within(letter).getByRole("button", { name: "Reject…" })).toBeEnabled();
  });

  it("shows why plg-api refused a decision, and keeps the action pending", async () => {
    plgApi();
    server.use(
      http.post(`/api/threads/${REMINDER.thread_id}/resume`, () =>
        HttpResponse.json({ detail: "That version of the action is not pending" }, { status: 409 }),
      ),
    );
    render(<ApprovalsScreen role="officer" />);

    const letter = await screen.findByRole("article", { name: REMINDER.title });
    await userEvent.click(within(letter).getByRole("button", { name: "Approve and send" }));

    expect(await within(letter).findByText("That version of the action is not pending")).toHaveAttribute("role", "alert");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(card(REMINDER.title)).toBeInTheDocument();
  });

  it("shows a run that failed while carrying out the decision", async () => {
    plgApi();
    const failed = `id: 1\nevent: error\ndata: {"type":"error","seq":1,"run_id":"r1","message":"Outbox unavailable"}\n\n`;
    server.use(http.post(`/api/threads/${REMINDER.thread_id}/resume`, () => sseResponse(failed)));
    render(<ApprovalsScreen role="officer" />);

    const letter = await screen.findByRole("article", { name: REMINDER.title });
    await userEvent.click(within(letter).getByRole("button", { name: "Approve and send" }));

    expect(await within(letter).findByText("It failed: Outbox unavailable")).toBeInTheDocument();
  });
});
