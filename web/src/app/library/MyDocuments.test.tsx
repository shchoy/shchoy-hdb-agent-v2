import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { when } from "@/app/dates";
import { LibraryScreen } from "@/app/library/LibraryScreen";
import type { MyDocuments } from "@/lib/events";
import { documentFixture } from "@/test/documents";
import { server } from "@/test/msw";
import { categoriesFixture, myDocumentsFixture, uploadFixture } from "@/test/sse";

const recorded = () => myDocumentsFixture("my_documents.json");
const [CHECKLIST, NOTE] = recorded().uploads;

/** GET /api/my-documents answers with `views` in turn (the last one again after that). */
function serve(...views: MyDocuments[]) {
  let n = 0;
  server.use(
    http.get("/api/my-documents", () => HttpResponse.json(views[Math.min(n++, views.length - 1)])),
    http.get("/api/categories", () => HttpResponse.json(categoriesFixture())),
  );
}

async function openTab(options: Parameters<typeof userEvent.setup>[0] = {}) {
  const user = userEvent.setup(options);
  const view = render(<LibraryScreen />);
  await user.click(screen.getByRole("tab", { name: "My documents" }));
  const list = await screen.findByRole("list", { name: "My documents" });
  const picker = view.container.querySelector<HTMLInputElement>('input[type="file"]')!;
  return { user, list, picker };
}

const card = (title: string) => screen.getByRole("article", { name: title });

beforeEach(() => sessionStorage.clear());

describe("Library → My documents (#106)", () => {
  it("is the third Library tab", async () => {
    serve(recorded());
    render(<LibraryScreen />);

    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Categories", "Audit findings", "My documents"]);
  });

  it("lists each upload with its type, file, size, date and the conversations that used it, against the space", async () => {
    serve(recorded());
    const { list } = await openTab();

    expect(within(list).getAllByRole("article")).toHaveLength(2);
    expect(within(list).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      CHECKLIST.title,
      NOTE.title,
    ]);
    const note = card(NOTE.title);
    expect(within(note).getByText("Text")).toBeInTheDocument();
    expect(within(note).getByText(NOTE.filename, { selector: "dd" })).toBeInTheDocument();
    expect(within(note).getByText("220 B")).toBeInTheDocument();
    expect(within(note).getByText(when(NOTE.uploaded_at))).toBeInTheDocument();
    const used = within(note).getByRole("list", { name: `Conversations that used ${NOTE.title}` });
    expect(within(used).getByRole("link", { name: NOTE.conversations[0].title })).toHaveAttribute("href", "/");
    expect(within(card(CHECKLIST.title)).getByText("Markdown")).toBeInTheDocument();
    expect(within(card(CHECKLIST.title)).getByText("Not used in a conversation yet")).toBeInTheDocument();

    expect(screen.getByText("342 B of 200 MB used")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "342 B of 200 MB used" })).toHaveAttribute("value", "342");
  });

  it("opens a conversation that used the upload on Ask", async () => {
    serve(recorded());
    const { user } = await openTab();

    await user.click(within(card(NOTE.title)).getByRole("link", { name: NOTE.conversations[0].title }));

    expect(sessionStorage.getItem("plg_active_thread")).toBe(NOTE.conversations[0].thread_id);
  });

  it("opens an upload in the source viewer, or says it was deleted", async () => {
    serve(recorded());
    const fixture = documentFixture("upload");
    server.use(
      http.get("/api/documents/:id", ({ params }) =>
        params.id === NOTE.upload_id
          ? HttpResponse.json(fixture.document)
          : HttpResponse.json({ detail: "Document not found" }, { status: 404 }),
      ),
    );
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Open ${NOTE.title}` }));
    expect(await screen.findByRole("region", { name: `Source: ${fixture.document.title}` })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: `Open ${CHECKLIST.title}` }));
    expect(await within(card(CHECKLIST.title)).findByRole("alert")).toHaveTextContent(
      "This upload was deleted, so it can't be opened.",
    );
  });

  it("renames an upload in place: Enter saves, then focus is back on Rename", async () => {
    serve(recorded());
    const bodies: unknown[] = [];
    server.use(
      http.patch("/api/uploads/:id", async ({ request, params }) => {
        bodies.push({ id: params.id, body: await request.json() });
        return HttpResponse.json({ ...NOTE, title: "Kiosk visit" });
      }),
    );
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Rename ${NOTE.title}` }));
    const field = screen.getByRole("textbox", { name: "Name" });
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "  Kiosk   visit{Enter}");

    expect(await screen.findByRole("article", { name: "Kiosk visit" })).toBeInTheDocument();
    expect(bodies).toEqual([{ id: NOTE.upload_id, body: { title: "Kiosk visit" } }]);
    expect(screen.getByRole("button", { name: "Rename Kiosk visit" })).toHaveFocus();
    expect(screen.getByText(`Renamed ${NOTE.title} to Kiosk visit`)).toBeInTheDocument();
  });

  it("cancels a rename with Escape", async () => {
    serve(recorded());
    let called = false;
    server.use(
      http.patch("/api/uploads/:id", () => {
        called = true;
        return HttpResponse.json(NOTE);
      }),
    );
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Rename ${NOTE.title}` }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), " changed{Escape}");

    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Rename ${NOTE.title}` })).toHaveFocus();
    expect(card(NOTE.title)).toBeInTheDocument();
    expect(called).toBe(false);
  });

  it("shows plg-api's reason when a rename is refused", async () => {
    serve(recorded());
    server.use(
      http.patch("/api/uploads/:id", () =>
        HttpResponse.json({ detail: "String should have at most 120 characters" }, { status: 422 }),
      ),
    );
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Rename ${NOTE.title}` }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), " again{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("String should have at most 120 characters");
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("aria-invalid", "true");
  });

  it("deletes an upload after a confirmation that starts on Cancel", async () => {
    const after = { ...recorded(), uploads: [CHECKLIST], used_bytes: CHECKLIST.size };
    serve(recorded(), after);
    const deleted: unknown[] = [];
    server.use(
      http.delete("/api/uploads/:id", ({ params }) => {
        deleted.push(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Delete ${NOTE.title}` }));
    const confirm = screen.getByRole("group", { name: `Delete ${NOTE.title}?` });
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByRole("article", { name: NOTE.title })).not.toBeInTheDocument());
    expect(deleted).toEqual([NOTE.upload_id]);
    expect(screen.getByText(`Deleted ${NOTE.title}`)).toBeInTheDocument();
    expect(screen.getByText("122 B of 200 MB used")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload files" })).toHaveFocus();
  });

  it("keeps the upload when the deletion is cancelled", async () => {
    serve(recorded());
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Delete ${NOTE.title}` }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("group", { name: `Delete ${NOTE.title}?` })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Delete ${NOTE.title}` })).toHaveFocus();
  });

  it("shows a refused deletion (404: gone elsewhere) and reloads the list", async () => {
    const after = { ...recorded(), uploads: [CHECKLIST] };
    serve(recorded(), after);
    server.use(http.delete("/api/uploads/:id", () => HttpResponse.json({ detail: "Upload not found" }, { status: 404 })));
    const { user } = await openTab();

    await user.click(screen.getByRole("button", { name: `Delete ${NOTE.title}` }));
    await user.click(within(screen.getByRole("group", { name: `Delete ${NOTE.title}?` })).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByRole("article", { name: NOTE.title })).not.toBeInTheDocument());
  });

  it("uploads files without a conversation, then lists them", async () => {
    const added = { ...uploadFixture(), upload_id: "upload-new", filename: "memo.txt", title: "memo.txt", conversations: [] };
    serve(recorded(), { ...recorded(), uploads: [added, ...recorded().uploads] });
    const sent: (string | null)[] = [];
    server.use(
      http.post("/api/uploads", ({ request }) => {
        sent.push(new URL(request.url).searchParams.get("filename"));
        return HttpResponse.json(added, { status: 201 });
      }),
    );
    const { user, picker } = await openTab();

    await user.upload(picker, new File(["A memo."], "memo.txt", { type: "text/plain" }));

    expect(await screen.findByRole("article", { name: "memo.txt" })).toBeInTheDocument();
    expect(sent).toEqual(["memo.txt"]);
    expect(screen.getByText("Uploaded memo.txt")).toBeInTheDocument();
  });

  it("shows plg-api's reason when an upload is refused", async () => {
    serve(recorded());
    server.use(
      http.post("/api/uploads", () =>
        HttpResponse.json({ detail: "budget.xlsx is not a type that can be uploaded." }, { status: 415 }),
      ),
    );
    const { user, picker } = await openTab({ applyAccept: false });

    await user.upload(picker, new File(["PK"], "budget.xlsx"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "budget.xlsx was not uploaded: budget.xlsx is not a type that can be uploaded.",
    );
  });

  it("says when there is nothing uploaded yet", async () => {
    serve({ uploads: [], used_bytes: 0, quota_bytes: recorded().quota_bytes });
    const user = userEvent.setup();
    render(<LibraryScreen />);
    await user.click(screen.getByRole("tab", { name: "My documents" }));

    expect(await screen.findByText(/You haven't uploaded any documents yet/)).toBeInTheDocument();
    expect(screen.getByText("0 B of 200 MB used")).toBeInTheDocument();
  });

  it("says when the list can't be loaded", async () => {
    server.use(
      http.get("/api/my-documents", () => HttpResponse.json({ detail: "no" }, { status: 502 })),
      http.get("/api/categories", () => HttpResponse.json(categoriesFixture())),
    );
    const user = userEvent.setup();
    render(<LibraryScreen />);
    await user.click(screen.getByRole("tab", { name: "My documents" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your documents.");
  });
});
