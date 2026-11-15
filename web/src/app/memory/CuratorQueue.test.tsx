import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { CuratorQueue } from "@/app/memory/CuratorQueue";
import { server } from "@/test/msw";
import { feedbackFixture } from "@/test/sse";

type Action = { action_id: string; version: number; action_type: string; payload: Record<string, string> };
const QUEUE = feedbackFixture("curation.json") as unknown as Action[];
const byType = (t: string) => QUEUE.find((a) => a.action_type === t)!;
const SQL = byType("approve_sql_example");
const EXAMPLE = byType("approve_example");
const FACT = byType("approve_team_fact");

/** Serves the recorded queue and records every decision posted. */
function curationApi(reply: () => Response = () => HttpResponse.json(feedbackFixture("decided.json"))) {
  const sent: unknown[] = [];
  server.use(
    http.get("/api/curation", () => HttpResponse.json(QUEUE)),
    http.post("/api/curation/decide", async ({ request }) => {
      sent.push(await request.json());
      return reply();
    }),
  );
  return sent;
}

async function queue(staffId = "S03") {
  const user = userEvent.setup();
  render(<CuratorQueue staffId={staffId} />);
  const list = await screen.findByRole("list", { name: "Curator queue" });
  return { user, list };
}

const card = (name: RegExp | string) => screen.getByRole("article", { name });

describe("Curator queue", () => {
  it("lists what answer feedback proposes, as plain text, with who proposed it", async () => {
    curationApi();
    const { list } = await queue();

    expect(within(list).getAllByRole("article")).toHaveLength(3);
    const sql = card("SQL example");
    expect(sql).toHaveTextContent(`Question: ${SQL.payload.question}`);
    expect(within(sql).getByText(SQL.payload.sql).tagName).toBe("PRE");
    expect(sql).toHaveTextContent("Proposed by S05");
    const example = card("Corrected answer");
    expect(example).toHaveTextContent(`Corrected answer: ${EXAMPLE.payload.answer}`);
    // The answer given is shown as written, markdown and all, never rendered as HTML.
    expect(example).toHaveTextContent(`Answer given: ${EXAMPLE.payload.original}`);
    expect(card("Team fact")).toHaveTextContent(`Proposed fact: ${FACT.payload.fact}`);
  });

  it("approves a proposal, then drops it from the queue and says so", async () => {
    const sent = curationApi();
    const { user } = await queue();

    await user.click(within(card("Team fact")).getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.queryByRole("article", { name: "Team fact" })).not.toBeInTheDocument());
    expect(sent).toEqual([{ action_id: FACT.action_id, version: FACT.version, decision: "approve" }]);
    expect(screen.getByRole("status", { name: "Results" })).toHaveTextContent(/approved/);
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("edits the SQL of an example before approving it", async () => {
    const sent = curationApi();
    const { user } = await queue();
    const sql = card("SQL example");

    await user.click(within(sql).getByRole("button", { name: "Edit" }));
    const field = within(sql).getByLabelText("SQL");
    await user.clear(field);
    await user.type(field, "SELECT 1");
    await user.click(within(sql).getByRole("button", { name: "Approve edited" }));

    await waitFor(() =>
      expect(sent).toEqual([
        { action_id: SQL.action_id, version: SQL.version, decision: "edit", edits: { sql: "SELECT 1" } },
      ]),
    );
  });

  it("needs a reason to reject", async () => {
    const sent = curationApi();
    const { user } = await queue();
    const example = card("Corrected answer");

    await user.click(within(example).getByRole("button", { name: "Reject" }));
    const confirm = within(example).getByRole("button", { name: "Confirm reject" });
    expect(confirm).toBeDisabled();
    await user.type(within(example).getByLabelText("Reason"), "The count was right.");
    await user.click(confirm);

    await waitFor(() =>
      expect(sent).toEqual([
        { action_id: EXAMPLE.action_id, version: EXAMPLE.version, decision: "reject", reason: "The count was right." },
      ]),
    );
  });

  it("lets the officer who proposed it only withdraw it", async () => {
    const sent = curationApi();
    const { user, list } = await queue("S05");

    expect(within(list).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    const fact = card("Team fact");
    await user.click(within(fact).getByRole("button", { name: "Withdraw" }));
    await user.type(within(fact).getByLabelText("Reason"), "I was wrong.");
    await user.click(within(fact).getByRole("button", { name: "Confirm withdraw" }));

    await waitFor(() =>
      expect(sent).toEqual([{ action_id: FACT.action_id, version: FACT.version, decision: "reject", reason: "I was wrong." }]),
    );
  });

  it("shows why a decision was refused and keeps the proposal", async () => {
    curationApi(() => HttpResponse.json({ detail: "That version is not pending" }, { status: 409 }));
    const { user } = await queue();

    await user.click(within(card("Team fact")).getByRole("button", { name: "Approve" }));

    expect(await within(card("Team fact")).findByRole("alert")).toHaveTextContent("That version is not pending");
  });

  it("says when nothing is waiting", async () => {
    server.use(http.get("/api/curation", () => HttpResponse.json([])));
    render(<CuratorQueue staffId="S03" />);

    expect(await screen.findByText("Nothing from answer feedback is waiting for review.")).toBeInTheDocument();
  });
});
