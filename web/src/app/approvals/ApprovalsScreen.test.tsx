import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApprovalsScreen } from "@/app/approvals/ApprovalsScreen";
import { server } from "@/test/msw";
import { approvalsFixture, sseResponse } from "@/test/sse";

// Recorded from plg-api (scripts/record_sse_fixtures.py): a feedback reply with an open slot and a phone number
// flagged, a complete arrears reminder and an i-EMS ticket for ambiguous feedback (electrical or seepage, low
// confidence), proposed in three conversations; then the ticket raised with edits, the reply edited, the reminder rejected.
const PENDING = approvalsFixture("pending.json");
const AUDIT = approvalsFixture("audit.json");
const [FEEDBACK, REMINDER, TICKET] = PENDING as { action_id: string; thread_id: string; title: string }[];
const [REJECTED, EDITED, RAISED] = AUDIT;
const RAISED_TICKET = (RAISED as { ticket: { ticket_id: string; feedback_id: string } }).ticket;

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
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const pending = await screen.findByRole("list", { name: "Pending approvals" });
    expect(within(pending).getAllByRole("article")).toHaveLength(3);

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
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    expect(await screen.findByText("Nothing is waiting for your approval.")).toBeInTheDocument();
  });

  it("sends an edited letter, showing each change as a diff, then the result and the audit trail", async () => {
    const sent = decisions(FEEDBACK.thread_id, approvalsFixture("edit.sse"), { pending: [REMINDER], audit: [EDITED] });
    render(<ApprovalsScreen role="officer" staffId="S05" />);

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
    render(<ApprovalsScreen role="officer" staffId="S05" />);

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
    const { unmount } = render(<ApprovalsScreen role="officer" staffId="S05" />);

    const reply = await screen.findByRole("article", { name: FEEDBACK.title });
    expect(within(reply).queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();
    expect(reply).toHaveTextContent("Fill the open slots (Edit slots) before the letter can be sent.");
    expect(within(card(REMINDER.title)).getByRole("button", { name: "Approve and send" })).toBeEnabled();
    unmount();

    render(<ApprovalsScreen role="analyst" staffId="S05" />);
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
    render(<ApprovalsScreen role="officer" staffId="S05" />);

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
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const letter = await screen.findByRole("article", { name: REMINDER.title });
    await userEvent.click(within(letter).getByRole("button", { name: "Approve and send" }));

    expect(await within(letter).findByText("It failed: Outbox unavailable")).toBeInTheDocument();
  });

  it("keeps a decision's result when the run fails afterwards", async () => {
    const after = `id: 9\nevent: error\ndata: {"type":"error","seq":9,"run_id":"r1","message":"Claude unavailable"}\n\n`;
    decisions(REMINDER.thread_id, approvalsFixture("reject.sse") + after, { pending: [FEEDBACK], audit: [REJECTED] });
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const letter = await screen.findByRole("article", { name: REMINDER.title });
    await userEvent.click(within(letter).getByRole("button", { name: "Reject…" }));
    await userEvent.type(within(letter).getByLabelText("Reason for rejecting"), "The tenant paid yesterday.");
    await userEvent.click(within(letter).getByRole("button", { name: "Reject" }));

    expect(await screen.findByRole("status")).toHaveTextContent(`${REMINDER.title}: rejected; nothing was sent.`);
  });

  it("keeps the inbox on screen when reloading it fails after a decision", async () => {
    decisions(REMINDER.thread_id, approvalsFixture("reject.sse"), { pending: [FEEDBACK], audit: [REJECTED] });
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const letter = await screen.findByRole("article", { name: REMINDER.title });
    server.use(http.get("/api/approvals", () => HttpResponse.json({ detail: "down" }, { status: 502 })));
    await userEvent.click(within(letter).getByRole("button", { name: "Reject…" }));
    await userEvent.type(within(letter).getByLabelText("Reason for rejecting"), "The tenant paid yesterday.");
    await userEvent.click(within(letter).getByRole("button", { name: "Reject" }));

    expect(await screen.findByRole("status")).toHaveTextContent("rejected; nothing was sent.");
    expect(await screen.findByText("Could not reload your approvals.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Pending approvals" })).toBeInTheDocument();
  });

  it("can't send edits while an open slot is still blank", async () => {
    plgApi();
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const reply = await screen.findByRole("article", { name: FEEDBACK.title });
    await userEvent.click(within(reply).getByRole("button", { name: "Edit slots" }));
    await userEvent.type(within(reply).getByLabelText("next_steps"), " Thanks.");

    expect(within(reply).getByRole("button", { name: "Send edited letter" })).toBeDisabled();
    expect(reply).toHaveTextContent("Fill action_taken before sending.");
  });

  it("shows a proposed i-EMS ticket with its classification, flagged when it is low confidence", async () => {
    plgApi();
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const ticket = await screen.findByRole("article", { name: TICKET.title });
    expect(ticket).toHaveTextContent("Raise i-EMS ticket: Electrical (High) for M&E");
    expect(ticket).toHaveTextContent("i-EMS ticket · version 1 · Feedback case FB-NEW-");
    expect(ticket).toHaveTextContent("Low confidence — please check");
    const classified = ticket.querySelector("dl");
    expect(classified).toHaveTextContent("CategoryElectrical (ELE)");
    expect(classified).toHaveTextContent("SeverityHigh");
    expect(classified).toHaveTextContent("TeamM&E");
    expect(classified).toHaveTextContent("VendorSunrise M&E Services Pte Ltd");
    expect(classified).toHaveTextContent("i-EMS SLA3 days");
    expect(classified).toHaveTextContent("Confidence50%");
    expect(within(ticket).getByRole("list", { name: "Other plausible categories" })).toHaveTextContent(
      "Water Seepage / Leak (SEP), Medium, 60%",
    );
    expect(ticket).toHaveTextContent("Rationale: 'Ceiling ... wet' reads as water seepage");
    expect(within(ticket).getByRole("row", { name: /Unit/ })).toHaveTextContent("not given");
    const frame = within(ticket).getByTitle("Ticket to raise: " + TICKET.title);
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain("Sunrise M&amp;E Services Pte Ltd");
    expect(within(ticket).getByRole("button", { name: "Approve and raise" })).toBeEnabled();
    expect(within(ticket).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("raises an edited ticket, showing each change as a diff, then the result and the raised ticket", async () => {
    const sent = decisions(TICKET.thread_id, approvalsFixture("ticket_edit.sse"), {
      pending: [FEEDBACK, REMINDER],
      audit: [RAISED],
    });
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const ticket = await screen.findByRole("article", { name: TICKET.title });
    await userEvent.click(within(ticket).getByRole("button", { name: "Edit ticket" }));
    const category = within(ticket).getByLabelText("Category");
    expect(within(category).getAllByRole("option").map((o) => o.getAttribute("value"))).toEqual([
      "STR", "SEP", "PLB", "ELE", "FIR", "PST",
    ]);
    await userEvent.selectOptions(category, "SEP");
    await userEvent.selectOptions(within(ticket).getByLabelText("Priority"), "High");
    await userEvent.type(within(ticket).getByLabelText("Unit"), "U-PI675-02-07");

    const changed = within(ticket).getByRole("row", { name: /Category/ });
    expect(changed.querySelector("del")).toHaveTextContent("Electrical (ELE)");
    expect(changed.querySelector("ins")).toHaveTextContent("Water Seepage / Leak (SEP)");
    expect(within(ticket).getByRole("row", { name: /Priority/ }).querySelector("ins")).toBeNull();
    const unit = within(ticket).getByRole("row", { name: /Unit/ });
    expect(unit.querySelector("del")).toBeNull();
    expect(unit.querySelector("ins")).toHaveTextContent("U-PI675-02-07");

    await userEvent.click(within(ticket).getByRole("button", { name: "Raise edited ticket" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent(
      `${TICKET.title}: raised with your edits as ${RAISED_TICKET.ticket_id} (version 2).`,
    );
    expect(sent).toEqual([{
      action_id: TICKET.action_id, version: 1, decision: "edit",
      // A new category is raised at the priority shown, not the category's default.
      edits: { category_code: "SEP", severity: "High", unit_id: "U-PI675-02-07" },
    }]);

    const trail = within(await screen.findByRole("list", { name: "Audit trail" })).getByRole("article");
    expect(trail).toHaveTextContent("Raised with edits by S05 (officer)");
    expect(trail).toHaveTextContent(`i-EMS ticket ${RAISED_TICKET.ticket_id} (version 2) raised`);
    const raised = trail.querySelector("dl");
    expect(raised).toHaveTextContent(`Feedback case${RAISED_TICKET.feedback_id}`);
    expect(raised).toHaveTextContent("CategoryWater Seepage / Leak (SEP)");
    expect(raised).toHaveTextContent("PriorityHigh");
    expect(raised).toHaveTextContent("TeamCivil & Structural");
    expect(raised).toHaveTextContent("VendorKemas Building Works Pte Ltd");
    expect(raised).toHaveTextContent("SLA3 days, due 16 Nov 2026");
    expect(raised).toHaveTextContent("UnitU-PI675-02-07");
    expect(trail).not.toHaveTextContent("Outbox item");
  });

  it("approves a ticket as proposed", async () => {
    // The recorded raise was an edit; as an approval, the same ticket is raised at the proposed version.
    const approved = approvalsFixture("ticket_edit.sse").replace('"version":2,"decision":"edit"', '"version":1,"decision":"approve"');
    const sent = decisions(TICKET.thread_id, approved, { pending: [FEEDBACK, REMINDER], audit: [] });
    render(<ApprovalsScreen role="officer" staffId="S05" />);

    const ticket = await screen.findByRole("article", { name: TICKET.title });
    await userEvent.click(within(ticket).getByRole("button", { name: "Approve and raise" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      `${TICKET.title}: raised as ${RAISED_TICKET.ticket_id} (version 1).`,
    );
    expect(sent).toEqual([{ action_id: TICKET.action_id, version: 1, decision: "approve" }]);
  });

  it("can't raise a ticket with a required field blanked, or for a role that can't raise it", async () => {
    plgApi();
    const { unmount } = render(<ApprovalsScreen role="officer" staffId="S05" />);

    const ticket = await screen.findByRole("article", { name: TICKET.title });
    await userEvent.click(within(ticket).getByRole("button", { name: "Edit ticket" }));
    await userEvent.clear(within(ticket).getByLabelText("Description"));
    expect(within(ticket).getByRole("button", { name: "Raise edited ticket" })).toBeDisabled();
    expect(ticket).toHaveTextContent("Fill Description before raising.");
    unmount();

    render(<ApprovalsScreen role="analyst" staffId="S05" />);
    const theirs = await screen.findByRole("article", { name: TICKET.title });
    expect(within(theirs).queryByRole("button", { name: "Approve and raise" })).not.toBeInTheDocument();
    expect(within(theirs).queryByRole("button", { name: "Edit ticket" })).not.toBeInTheDocument();
    expect(theirs).toHaveTextContent("Your role can't raise this ticket. You can reject it with a reason.");
  });

  describe("a glossary change", () => {
    // Recorded: S02 (policy owner) proposes that vacant units include those under tender again from 1 Oct 2026; the
    // term owner S08 (Kelvin Goh, analyst) sees it in their inbox and approves it.
    const [CHANGE] = approvalsFixture("glossary_pending.json") as { action_id: string; thread_id: string; title: string }[];
    const [ADOPTED] = approvalsFixture("glossary_audit.json");

    function glossaryApi(stream = approvalsFixture("glossary_approve.sse")) {
      const sent: unknown[] = [];
      let state: Decided = { pending: [CHANGE], audit: [] };
      server.use(
        http.get("/api/approvals", () => HttpResponse.json(state.pending)),
        http.get("/api/audit", () => HttpResponse.json(state.audit)),
        http.post(`/api/threads/${CHANGE.thread_id}/resume`, async ({ request }) => {
          sent.push(await request.json());
          state = { pending: [], audit: [ADOPTED] };
          return sseResponse(stream);
        }),
      );
      return sent;
    }

    it("shows the term owner the definition in force against the proposed one, and adopts it", async () => {
      const sent = glossaryApi();
      render(<ApprovalsScreen role="analyst" staffId="S08" />);

      const change = await screen.findByRole("article", { name: CHANGE.title });
      expect(change).toHaveTextContent("Glossary change · version 1 · Vacant unit (plg:Vacant)");
      expect(within(change).getByRole("columnheader", { name: "Now (plg:Vacant_v2)" })).toBeInTheDocument();
      expect(within(change).getByRole("columnheader", { name: "Proposed (plg:Vacant_v3)" })).toBeInTheDocument();
      const definition = within(change).getByRole("row", { name: /Definition/ });
      expect(definition.querySelector("del")).toHaveTextContent("excluding units under tender");
      expect(definition.querySelector("ins")).toHaveTextContent(
        "Lettable unit with no active or committed tenancy, including units under tender.",
      );
      const value = within(change).getByRole("row", { name: /Value/ });
      expect(value.querySelector("del")).toHaveTextContent("excludes units under tender");
      expect(value.querySelector("ins")).toHaveTextContent("includes units under tender");
      expect(within(change).getByRole("row", { name: /Effective from/ })).toHaveTextContent("from 15 Apr 20261 Oct 2026");
      expect(change).toHaveTextContent("Reason: Management Meeting 5/2026 aligned the monthly report with the QBR.");
      expect(within(change).getByLabelText("SQL binding")).toHaveTextContent("WHERE u.status IN ('Vacant', 'Under Tender')");
      expect(change).toHaveTextContent("Term owner: Kelvin Goh (S08)");
      expect(change).not.toHaveTextContent("Waiting for");

      await userEvent.click(within(change).getByRole("button", { name: "Approve change" }));

      expect(await screen.findByRole("status")).toHaveTextContent(`${CHANGE.title}: adopted as plg:Vacant_v3 (version 1).`);
      expect(sent).toEqual([{ action_id: CHANGE.action_id, version: 1, decision: "approve" }]);
      const trail = within(await screen.findByRole("list", { name: "Audit trail" })).getByRole("article");
      expect(trail).toHaveTextContent("Approved and adopted by S08 (analyst)");
      expect(trail).toHaveTextContent("Adopted as glossary term plg:Vacant_v3.");
      expect(trail).not.toHaveTextContent("sent");
    });

    it("lets the proposer only withdraw it, waiting for the term owner", async () => {
      const sent = glossaryApi(approvalsFixture("glossary_approve.sse").replace(
        '"decision":"approve","outbox_id":null,"ticket_id":null,"term_id":"plg:Vacant_v3"',
        '"decision":"reject","outbox_id":null,"ticket_id":null,"term_id":null',
      ));
      render(<ApprovalsScreen role="director" staffId="S02" />);

      const change = await screen.findByRole("article", { name: CHANGE.title });
      expect(change).toHaveTextContent("Waiting for Kelvin Goh to approve.");
      expect(within(change).queryByRole("button", { name: "Approve change" })).not.toBeInTheDocument();
      expect(within(change).queryByRole("button", { name: "Edit change" })).not.toBeInTheDocument();

      await userEvent.click(within(change).getByRole("button", { name: "Withdraw…" }));
      await userEvent.type(within(change).getByLabelText("Reason for withdrawing"), "Wrong start date.");
      await userEvent.click(within(change).getByRole("button", { name: "Withdraw" }));

      expect(await screen.findByRole("status")).toHaveTextContent(`${CHANGE.title}: rejected; nothing was changed.`);
      expect(sent).toEqual([{ action_id: CHANGE.action_id, version: 1, decision: "reject", reason: "Wrong start date." }]);
    });

    it("sends the term owner's edits to the definition, value and effective date", async () => {
      const sent = glossaryApi(approvalsFixture("glossary_approve.sse").replace('"decision":"approve"', '"decision":"edit"'));
      render(<ApprovalsScreen role="analyst" staffId="S08" />);

      const change = await screen.findByRole("article", { name: CHANGE.title });
      await userEvent.click(within(change).getByRole("button", { name: "Edit change" }));
      const definition = within(change).getByLabelText("Definition");
      await userEvent.clear(definition);
      expect(within(change).getByRole("button", { name: "Adopt edited change" })).toBeDisabled();
      expect(change).toHaveTextContent("Fill Definition before adopting.");
      await userEvent.type(definition, "Lettable unit with no active tenancy, including units under tender.");
      const value = within(change).getByLabelText("Value");
      await userEvent.clear(value);
      await userEvent.type(value, "includes tender units");
      const starts = within(change).getByLabelText("Effective from");
      await userEvent.clear(starts);
      await userEvent.type(starts, "2026-11-01");

      const changed = within(change).getByRole("row", { name: /Effective from/ });
      expect(changed.querySelector("del")).toHaveTextContent("1 Oct 2026");
      expect(changed.querySelector("ins")).toHaveTextContent("1 Nov 2026");
      await userEvent.click(within(change).getByRole("button", { name: "Adopt edited change" }));

      expect(await screen.findByRole("status")).toHaveTextContent(
        `${CHANGE.title}: adopted with your edits as plg:Vacant_v3 (version 1).`,
      );
      expect(sent).toEqual([{
        action_id: CHANGE.action_id, version: 1, decision: "edit",
        edits: {
          definition: "Lettable unit with no active tenancy, including units under tender.",
          value: "includes tender units",
          effective_from: "2026-11-01",
        },
      }]);
    });
  });
});
