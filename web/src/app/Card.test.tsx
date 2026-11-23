import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge, Card, TableScroll } from "@/app/Card";
import { DocCheckCard, type DocCheck } from "@/app/DocCheckCard";
import { InjectionAlert } from "@/app/InjectionAlert";
import { TaskList } from "@/app/TaskList";
import type { TaskDigest } from "@/lib/events";

describe("Card", () => {
  it("is a region named by its heading, with status badges in its header and the body below", () => {
    render(
      <Card heading="Document check" badges={<Badge tone="success">Complete</Badge>}>
        <p>Body text</p>
      </Card>,
    );

    const card = screen.getByRole("region", { name: "Document check" });
    expect(within(card).getByRole("heading", { level: 3, name: "Document check" })).toBeInTheDocument();
    expect(within(card).getByText("Complete")).toHaveAttribute("data-tone", "success");
    expect(card).toHaveTextContent(/^Document checkCompleteBody text$/);
  });

  it("takes a heading level, and becomes an alert without a heading", () => {
    const { rerender } = render(
      <Card heading="Policy stance" level={4}>
        <p>x</p>
      </Card>,
    );
    expect(screen.getByRole("heading", { level: 4, name: "Policy stance" })).toBeInTheDocument();

    rerender(
      <Card role="alert" tone="danger">
        <p>Planted text</p>
      </Card>,
    );
    expect(screen.getByRole("alert")).toHaveAttribute("data-tone", "danger");
  });

  it("puts a table in a named, keyboard-focusable region so it can scroll sideways", () => {
    render(
      <TableScroll label="Checklist">
        <table>
          <tbody>
            <tr>
              <td>x</td>
            </tr>
          </tbody>
        </table>
      </TableScroll>,
    );
    const region = screen.getByRole("region", { name: "Checklist" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getByRole("table")).toBeInTheDocument();
  });
});

const check: DocCheck = {
  application_id: "APP-1",
  app_type: "REN",
  app_type_label: "Renewal",
  tenant_name: "Golden Leaf",
  unit_id: "U-1",
  unit_address: "Blk 1 #01-01",
  submitted_date: "2026-09-01",
  complete: false,
  checklist: [
    {
      doc_code: "BIZ",
      label: "ACRA profile",
      mandatory: true,
      status: "ok",
      files: ["a.pdf"],
      problem: null,
      reason: null,
    },
    {
      doc_code: "INS",
      label: "Insurance certificate",
      mandatory: true,
      status: "problem",
      files: ["b.pdf"],
      problem: "expired",
      reason: "lapsed",
    },
  ],
  files: [],
} as unknown as DocCheck;

describe("results in the shared card style", () => {
  it("document check: status badge, a scrolling checklist, problem lines marked in words", () => {
    render(<DocCheckCard check={check} />);
    const card = screen.getByRole("region", { name: "Document check" });
    expect(within(card).getByText("Incomplete")).toHaveAttribute("data-tone", "danger");
    const scroll = within(card).getByRole("region", { name: "Checklist" });
    const problem = within(scroll).getByRole("rowheader", { name: "Insurance certificate" }).closest("tr")!;
    expect(problem).toHaveTextContent("Expired: lapsed");
    expect(within(problem).getByRole("img", { name: "Problem" })).toBeInTheDocument();
  });

  it("tasks: an overdue badge in words, in a scrolling table", () => {
    const digest = {
      staff_id: "S04",
      name: "Siti",
      title: "Leasing Officer",
      as_of: "2026-09-30",
      open_count: 1,
      overdue_count: 1,
      tasks: [
        {
          rank: 1,
          task_id: "TSK-1",
          title: "Renew",
          task_type: "renewal",
          due_date: "2026-09-01",
          overdue: true,
          days_overdue: 29,
          urgency: "overdue",
          impact: "high",
          score: 12,
          reasons: ["Overdue"],
        },
      ],
    } as unknown as TaskDigest;
    render(<TaskList digest={digest} />);
    const card = screen.getByRole("region", { name: "Top tasks" });
    const scroll = within(card).getByRole("region", { name: "Ranked tasks" });
    expect(within(scroll).getByText("Overdue · 29 days")).toHaveAttribute("data-tone", "danger");
  });

  it("injection alert: still one alert, in the danger tone", () => {
    render(
      <InjectionAlert flags={[{ source: "message", rules: ["override"], doc_id: null, title: null, excerpt: "x" }]} />,
    );
    expect(screen.getByRole("alert")).toHaveAttribute("data-tone", "danger");
  });
});
