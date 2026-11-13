import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { DocCheckScreen } from "@/app/doc-check/DocCheckScreen";
import { server } from "@/test/msw";
import { fixture, sseResponse, submissionsFixture } from "@/test/sse";

const QUESTION = "Is application APP-2026-0294 complete? Check the submitted documents.";

beforeEach(() => {
  sessionStorage.clear();
  server.use(http.get("/api/submissions", () => HttpResponse.json(submissionsFixture())));
});

async function checkFinished() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Check APP-2026-0294" })).toBeEnabled(), {
    timeout: 5000,
  });
}

describe("Document check screen", () => {
  it("lists the applications with a submission bundle", async () => {
    render(<DocCheckScreen />);

    const table = await screen.findByRole("table", { name: "Applications" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(submissionsFixture().length);
    expect(rows[1]).toHaveTextContent(/APP-2026-0294Alteration & additionSiva Dental Care Pte LtdU-PI642-01-0122 Sept? 2026Pending Documents3/);
  });

  it("checks the picked application in a new conversation, then shows the checklist, the notice and a link to Approvals", async () => {
    const runs: { thread: string | readonly string[] | undefined; body: unknown }[] = [];
    server.use(
      http.post("/api/threads", () => HttpResponse.json({ thread_id: "t9" }, { status: 201 })),
      http.post("/api/threads/:id/runs", async ({ params, request }) => {
        runs.push({ thread: params.id, body: await request.json() });
        return sseResponse(fixture("doc_check"));
      }),
    );
    const user = userEvent.setup();
    render(<DocCheckScreen />);

    await user.click(await screen.findByRole("button", { name: "Check APP-2026-0294" }));
    await checkFinished();

    expect(runs).toEqual([{ thread: "t9", body: { message: QUESTION } }]);
    const result = screen.getByRole("region", { name: "Check of APP-2026-0294" });
    expect(result).toHaveTextContent("APP-2026-0294 is incomplete");
    const card = within(result).getByRole("region", { name: "Document check" });
    expect(card).toHaveTextContent("Incomplete");
    const checklist = within(card).getByRole("table", { name: "Checklist" });
    expect(within(checklist).getAllByRole("img", { name: "Missing" })).toHaveLength(2);
    expect(within(checklist).getAllByRole("img", { name: "Submitted" })).toHaveLength(3);
    expect(within(result).getByRole("region", { name: "Draft preview" })).toHaveTextContent("Missing Documents Notice");
    expect(within(result).getByRole("link", { name: "Review the notice in Approvals" })).toHaveAttribute(
      "href",
      "/approvals",
    );

    await user.click(within(result).getByRole("link", { name: "Open the conversation" }));
    expect(sessionStorage.getItem("plg_active_thread")).toBe("t9");
  });

  it("says the check failed when the run reports an error", async () => {
    server.use(
      http.post("/api/threads", () => HttpResponse.json({ thread_id: "t9" }, { status: 201 })),
      http.post("/api/threads/:id/runs", () => sseResponse(fixture("error"))),
    );
    const user = userEvent.setup();
    render(<DocCheckScreen />);

    await user.click(await screen.findByRole("button", { name: "Check APP-2026-0294" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The check is incomplete and must not be trusted.");
    expect(screen.queryByRole("link", { name: "Review the notice in Approvals" })).not.toBeInTheDocument();
  });

  it("says when the applications can't be loaded", async () => {
    server.use(http.get("/api/submissions", () => HttpResponse.json({ detail: "Not signed in" }, { status: 401 })));
    render(<DocCheckScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the applications.");
  });
});
