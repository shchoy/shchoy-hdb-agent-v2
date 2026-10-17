import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { SourceViewer } from "@/app/SourceViewer";
import type { CitationEvent } from "@/lib/events";
import { documentFixture, type DocumentFixture } from "@/test/documents";
import { server } from "@/test/msw";

function citationFor({ document, location, start, end }: DocumentFixture): CitationEvent {
  return {
    type: "citation", seq: 1, index: 1, doc_id: document.doc_id, chunk_id: location.chunk_id,
    title: document.title, version: document.version, location: location.location,
    quote: location.quote, span: { start, end },
  };
}

function serve(fixture: DocumentFixture) {
  const spans: string[] = [];
  server.use(
    http.get("/api/documents/:id", () => HttpResponse.json(fixture.document)),
    http.get("/api/documents/:id/chunks/:chunk", ({ request }) => {
      spans.push(new URL(request.url).search);
      return HttpResponse.json(fixture.location);
    }),
  );
  return spans;
}

async function open(fixture: DocumentFixture) {
  const user = userEvent.setup();
  const { container } = render(<SourceViewer citation={citationFor(fixture)} />);
  await user.click(screen.getByRole("button", { name: "Open source" }));
  const viewer = await screen.findByRole("region", { name: `Source: ${fixture.document.title}` });
  return { viewer, container, user };
}

const flat = (text: string | null) => (text ?? "").replace(/\s+/g, " ").trim();

describe.each(["pdf", "docx", "email", "markdown"] as const)("Source viewer for a %s", (kind) => {
  it("shows the document with the cited span highlighted", async () => {
    const fixture = documentFixture(kind);
    serve(fixture);

    const { viewer } = await open(fixture);

    const marks = Array.from(viewer.querySelectorAll("mark"));
    expect(marks.length).toBeGreaterThan(0);
    expect(flat(marks.map((m) => m.textContent).join(" "))).toBe(flat(fixture.location.quote));
    // The rest of the document is there around the highlight.
    const text = fixture.document.blocks.find((b) => b.text !== fixture.location.quote)!.text;
    expect(viewer).toHaveTextContent(flat(text.split("\n")[0]));
  });
});

describe("Source viewer", () => {
  it("asks for the cited span of the chunk", async () => {
    const fixture = documentFixture("docx");
    const spans = serve(fixture);

    await open(fixture);

    expect(spans).toEqual([`?start=${fixture.start}&end=${fixture.end}`]);
  });

  it("shows PDF pages, and links to the original PDF at the cited page", async () => {
    const fixture = documentFixture("pdf");
    serve(fixture);

    const { viewer } = await open(fixture);

    const page = fixture.location.page!;
    expect(page).toBeGreaterThan(1);
    expect(within(viewer).getByRole("heading", { name: `Page ${page}` })).toBeInTheDocument();
    const link = within(viewer).getByRole("link", { name: /Open original PDF/ });
    expect(link).toHaveAttribute("href", `/api/documents/${fixture.document.doc_id}/file#page=${page}`);
  });

  it("offers other file types as a download, not inline", async () => {
    const fixture = documentFixture("email");
    serve(fixture);

    const { viewer } = await open(fixture);

    const link = within(viewer).getByRole("link", { name: /Download original/ });
    expect(link).toHaveAttribute("href", `/api/documents/${fixture.document.doc_id}/file`);
    expect(link).toHaveAttribute("download", fixture.document.filename);
  });

  it("renders raw HTML in a document as inert text", async () => {
    const fixture = documentFixture("email");
    const hostile = '<p>Hi</p><script>alert(1)</script><img src=x onerror="alert(2)">';
    fixture.document = {
      ...fixture.document,
      blocks: [{ text: `Please see ${hostile}`, level: 0, page: null }],
    };
    fixture.location = {
      ...fixture.location, quote: "Please see",
      highlights: [{ block: 0, start: 0, end: 10 }],
    };
    serve(fixture);

    const { viewer, container } = await open(fixture);

    expect(viewer).toHaveTextContent(hostile);
    expect(container.querySelector("script, img, p p")).toBeNull();
    expect(flat(viewer.querySelector("mark")!.textContent)).toBe("Please see");
  });

  it("falls back to the quote when the span can't be found in the file", async () => {
    const fixture = documentFixture("docx");
    fixture.location = { ...fixture.location, highlights: [], page: null };
    serve(fixture);

    const { viewer } = await open(fixture);

    expect(viewer.querySelector("mark")).toBeNull();
    expect(within(viewer).getByRole("note")).toHaveTextContent(fixture.location.quote);
  });

  it("says so when the source can't be loaded", async () => {
    const fixture = documentFixture("docx");
    server.use(
      http.get("/api/documents/:id", () => HttpResponse.json({ detail: "Document not found" }, { status: 404 })),
      http.get("/api/documents/:id/chunks/:chunk", () => HttpResponse.json({ detail: "x" }, { status: 404 })),
    );
    const user = userEvent.setup();
    render(<SourceViewer citation={citationFor(fixture)} />);

    await user.click(screen.getByRole("button", { name: "Open source" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("source could not be loaded");
    await waitFor(() => expect(screen.getByRole("button", { name: "Open source" })).toBeEnabled());
  });

  it("closes", async () => {
    const fixture = documentFixture("docx");
    serve(fixture);
    const { viewer, user } = await open(fixture);

    await user.click(within(viewer).getByRole("button", { name: "Close source" }));

    expect(screen.queryByRole("region", { name: /^Source:/ })).not.toBeInTheDocument();
  });
});
