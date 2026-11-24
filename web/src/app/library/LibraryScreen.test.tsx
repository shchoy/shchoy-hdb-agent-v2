import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { when } from "@/app/dates";
import { LibraryScreen } from "@/app/library/LibraryScreen";
import type { Categorisation } from "@/lib/events";
import { documentFixture } from "@/test/documents";
import { server } from "@/test/msw";
import { categoriesFixture } from "@/test/sse";

const POLICIES = "Tenancy Renewal & Security Deposit";

function serve(body: Categorisation | { detail: string }, status = 200) {
  server.use(http.get("/api/categories", () => HttpResponse.json(body, { status })));
}

async function categoryList() {
  return screen.findByRole("list", { name: "Document categories" });
}

describe("Library screen", () => {
  it("lists the categories with their document counts and descriptions, collapsed", async () => {
    const view = categoriesFixture();
    serve(view);
    render(<LibraryScreen />);

    const list = await categoryList();
    expect(screen.getByText(`Categorised on ${when(view.categorised_at!)}`)).toBeInTheDocument();
    const headings = within(list).getAllByRole("heading", { level: 2 });
    expect(headings.map((h) => h.textContent)).toEqual([
      ...view.categories.map((c) => `${c.name} (${c.documents.length} documents)`),
      `Uncategorised (${view.uncategorised.length} documents)`,
    ]);
    const policies = view.categories.find((c) => c.name === POLICIES)!;
    expect(within(list).getByText(policies.description)).toBeInTheDocument();
    for (const button of within(list).getAllByRole("button")) expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: POLICIES })).not.toBeInTheDocument();
  });

  it("shows each category as a card named by its heading", async () => {
    const view = categoriesFixture();
    serve(view);
    render(<LibraryScreen />);

    const list = await categoryList();
    const cards = within(list).getAllByRole("article");
    expect(cards).toHaveLength(view.categories.length + 1);
    expect(cards[0]).toHaveAccessibleName(`${view.categories[0].name} (${view.categories[0].documents.length} documents)`);
  });

  it("expands a category to its summary and documents, marking superseded versions", async () => {
    const user = userEvent.setup();
    const policies = categoriesFixture().categories.find((c) => c.name === POLICIES)!;
    serve(categoriesFixture());
    render(<LibraryScreen />);
    await categoryList();

    const toggle = screen.getByRole("button", { name: POLICIES });
    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByRole("region", { name: POLICIES });
    expect(panel).toHaveTextContent(policies.summary);
    const items = within(within(panel).getByRole("list", { name: `Documents in ${POLICIES}` })).getAllByRole("listitem");
    expect(items).toHaveLength(policies.documents.length);
    const old = items.find((i) => i.textContent?.includes("Rental Arrears Management Policy (v1.0)"))!;
    expect(old).toHaveTextContent(/policy\s*Superseded/);
    const current = items.find((i) => i.textContent?.includes("Rental Arrears Management Policy (v2.0)"))!;
    expect(current).not.toHaveTextContent("Superseded");

    await user.click(toggle);
    expect(screen.queryByRole("region", { name: POLICIES })).not.toBeInTheDocument();
  });

  it("opens a document of a category in place", async () => {
    const user = userEvent.setup();
    const fixture = documentFixture("docx");
    const asked: string[] = [];
    serve(categoriesFixture());
    server.use(
      http.get("/api/documents/:id", ({ params }) => {
        asked.push(String(params.id));
        return HttpResponse.json(fixture.document);
      }),
    );
    render(<LibraryScreen />);
    await categoryList();

    await user.click(screen.getByRole("button", { name: POLICIES }));
    await user.click(screen.getByRole("button", { name: `Open ${fixture.document.title}` }));

    const viewer = await screen.findByRole("region", { name: `Source: ${fixture.document.title}` });
    expect(viewer).toHaveTextContent(fixture.document.blocks[1].text.split("\n")[0]);
    expect(viewer).not.toHaveTextContent("The cited text is no longer found");
    expect(asked).toEqual([fixture.document.doc_id]);
  });

  it("lists the uncategorised documents last", async () => {
    const user = userEvent.setup();
    const view = categoriesFixture();
    serve(view);
    render(<LibraryScreen />);
    const list = await categoryList();

    const groups = within(list).getAllByRole("heading", { level: 2 });
    expect(groups.at(-1)).toHaveTextContent("Uncategorised");
    await user.click(screen.getByRole("button", { name: "Uncategorised" }));

    const items = within(screen.getByRole("list", { name: "Documents in Uncategorised" })).getAllByRole("listitem");
    expect(items.map((i) => i.querySelector("span")?.textContent)).toEqual(view.uncategorised.map((d) => d.title));
  });

  it("says when the documents have not been categorised yet", async () => {
    const view = categoriesFixture();
    const never: Categorisation = {
      categorised_at: null,
      categories: [],
      uncategorised: [...view.categories.flatMap((c) => c.documents), ...view.uncategorised],
    };
    serve(never);
    render(<LibraryScreen />);
    const list = await categoryList();

    expect(screen.getByRole("note")).toHaveTextContent(
      "The documents haven't been categorised yet. An administrator runs plg categorise to group them.",
    );
    expect(screen.queryByText(/^Categorised on/)).not.toBeInTheDocument();
    expect(within(list).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      `Uncategorised (${never.uncategorised.length} documents)`,
    ]);
  });

  it("shows an error when the categories cannot be loaded", async () => {
    serve({ detail: "boom" }, 502);
    render(<LibraryScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the library.");
    expect(screen.queryByRole("list", { name: "Document categories" })).not.toBeInTheDocument();
  });
});
