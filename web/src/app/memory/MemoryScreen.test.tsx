import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { MemoryScreen } from "@/app/memory/MemoryScreen";
import { server } from "@/test/msw";

const NOTE = {
  id: "preference-1", kind: "preference", text: "Prefers tables", status: "active",
  provenance: "Your conversation ab12cd34, 2026-11-07", confidence: 0.8,
  created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z", expires_at: null,
};

describe("Memory screen", () => {
  it("lists memories with where each came from, and flags policy conflicts", async () => {
    server.use(
      http.get("/api/memory", () =>
        HttpResponse.json([NOTE, { ...NOTE, id: "p2", text: "LOD at 90 days", status: "pending_review" }]),
      ),
    );
    render(<MemoryScreen />);

    const list = await screen.findByRole("list", { name: "Memories" });
    const [note, flagged] = within(list).getAllByRole("article");
    expect(within(note).getByRole("heading", { level: 3 })).toHaveTextContent("Preference");
    expect(note).toHaveTextContent("Prefers tables");
    expect(note).toHaveTextContent("From: Your conversation ab12cd34, 2026-11-07");
    expect(within(note).queryByText("Not in use")).not.toBeInTheDocument();
    expect(within(note).getByRole("button", { name: "Forget" })).toHaveAttribute("data-variant", "danger");
    expect(within(flagged).getByText("Not in use")).toHaveAttribute("data-tone", "warning");
    expect(screen.getAllByText(/Your conversation ab12cd34/)).toHaveLength(2);
    expect(within(flagged).getByRole("status")).toHaveTextContent("conflicts with current policy");
    expect(screen.getByRole("status")).toHaveTextContent("Edit it to make the exception clear, or forget it");
    expect(screen.queryByRole("button", { name: /keep using/i })).not.toBeInTheDocument();
  });

  it("forgets a memory", async () => {
    let notes = [NOTE];
    server.use(
      http.get("/api/memory", () => HttpResponse.json(notes)),
      http.delete("/api/memory/:id", () => {
        notes = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<MemoryScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "Forget" }));

    await waitFor(() => expect(screen.getByText("Nothing remembered yet.")).toBeInTheDocument());
  });

  it("edits a memory", async () => {
    const sent: unknown[] = [];
    server.use(
      http.get("/api/memory", () => HttpResponse.json([NOTE])),
      http.patch("/api/memory/:id", async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json({ ...NOTE, text: "Prefers lists" });
      }),
    );
    render(<MemoryScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const input = screen.getByLabelText("Memory text");
    await userEvent.clear(input);
    await userEvent.type(input, "Prefers lists");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sent).toEqual([{ text: "Prefers lists" }]));
  });
});
