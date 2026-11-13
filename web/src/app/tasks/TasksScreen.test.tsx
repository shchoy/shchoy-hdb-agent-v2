import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { TasksScreen } from "@/app/tasks/TasksScreen";
import { server } from "@/test/msw";
import { tasksFixture } from "@/test/sse";

/** Every digest query the screen made, as `staff_id` / `limit` pairs. */
let queries: { staff_id: string | null; limit: string | null }[];

beforeEach(() => {
  queries = [];
  server.use(
    http.get("/api/tasks/team", () => HttpResponse.json(tasksFixture("team.json"))),
    http.get("/api/tasks/digest", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const staffId = params.get("staff_id");
      queries.push({ staff_id: staffId, limit: params.get("limit") });
      if (staffId === "S06") return HttpResponse.json(tasksFixture("digest_S06.json"));
      if (staffId) return HttpResponse.json({ detail: "Your role can't view this officer's tasks" }, { status: 403 });
      return HttpResponse.json(tasksFixture("digest.json"));
    }),
  );
});

function rowFor(table: HTMLElement, taskId: string): HTMLElement {
  return within(table).getByRole("rowheader", { name: new RegExp(`^${taskId}`) }).closest("tr")!;
}

describe("Tasks screen", () => {
  it("shows the officer's own top tasks, ranked, with the overdue ones marked", async () => {
    render(<TasksScreen />);

    const list = await screen.findByRole("region", { name: "Top tasks for Marcus Lim" });
    expect(list.querySelector("dl")).toHaveTextContent(
      /OfficerMarcus Lim \(Estate Manager \(East\)\)As of30 Sept? 2026Open35Overdue26/,
    );
    const table = within(list).getByRole("table", { name: "Ranked tasks" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveTextContent("1TSK-2026-0830 Follow up Fire Safety at U-BV204-01-03Inspection Follow-up");
    expect(rows[0]).toHaveTextContent(/18 Sept? 2026 Overdue · 12 days/);
    expect(rows[0]).toHaveTextContent("Overdue × high impact = 12");
    expect(within(rows[0]).getByRole("list", { name: "Why TSK-2026-0830" })).toHaveTextContent(
      "Overdue by 12 days (due 18 Sep 2026)Safety-related",
    );
    const dueSoon = rowFor(table, "TSK-2026-0968");
    expect(dueSoon).not.toHaveTextContent("Overdue");
    expect(dueSoon).toHaveTextContent("This week × high impact = 9");
    expect(queries).toEqual([{ staff_id: null, limit: "5" }]);
  });

  it("lets a team lead switch to a team member's tasks", async () => {
    const user = userEvent.setup();
    render(<TasksScreen />);
    await screen.findByRole("region", { name: "Top tasks for Marcus Lim" });

    const officer = screen.getByLabelText("Officer");
    expect(within(officer).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Marcus Lim (you)",
      "Daniel Ong",
      "Ahmad Faizal Ismail",
    ]);
    await user.selectOptions(officer, "S06");
    await user.selectOptions(screen.getByLabelText("Show"), "50");

    const list = await screen.findByRole("region", { name: "Top tasks for Daniel Ong" });
    const table = within(list).getByRole("table", { name: "Ranked tasks" });
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(50);
    const structural = rowFor(table, "TSK-2026-0459");
    expect(structural).toHaveTextContent("Follow up Structural Defect at U-KR372-01-08");
    expect(within(structural).getByText("Overdue · 95 days").tagName).toBe("STRONG");
    expect(rowFor(table, "TSK-2026-0948")).toHaveTextContent("Overdue · 1 day");
    const luckyStar = rowFor(table, "TSK-2026-0452"); // the Lucky Star subletting follow-up
    expect(luckyStar).toHaveTextContent("Follow up Unauth Sublet at U-RH455-01-20");
    expect(luckyStar).toHaveTextContent("Overdue · 92 days");
    expect(rowFor(table, "TSK-2026-0953")).not.toHaveTextContent("Overdue ·");
    expect(queries.at(-1)).toEqual({ staff_id: "S06", limit: "50" });
  });

  it("says so when the officer's role can't view that officer's tasks", async () => {
    const user = userEvent.setup();
    render(<TasksScreen />);
    await screen.findByRole("region", { name: "Top tasks for Marcus Lim" });

    await user.selectOptions(screen.getByLabelText("Officer"), "S10");

    expect(await screen.findByRole("alert")).toHaveTextContent("Your role can't view this officer's tasks.");
    expect(screen.queryByRole("table", { name: "Ranked tasks" })).not.toBeInTheDocument();
  });

  it("offers no officer choice to someone who can only see their own tasks", async () => {
    server.use(
      http.get("/api/tasks/team", () => HttpResponse.json([tasksFixture("team.json")[0]])),
    );
    render(<TasksScreen />);

    await screen.findByRole("region", { name: "Top tasks for Marcus Lim" });
    expect(screen.queryByLabelText("Officer")).not.toBeInTheDocument();
  });
});
