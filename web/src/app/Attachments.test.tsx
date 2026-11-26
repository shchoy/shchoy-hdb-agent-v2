import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AskScreen } from "@/app/AskScreen";
import { DRAG_TYPE } from "@/app/shell/menu";
import { documentFixture } from "@/test/documents";
import { server } from "@/test/msw";
import { fixture, sseResponse, uploadFixture, uploadRefusedFixture } from "@/test/sse";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

/** The question upload.sse answers, citing the attached site-visit note (scripts/record_sse_fixtures.py `upload`). */
const QUESTION = "What did we agree with the kiosk tenant at unit 01-17?";
const NOTE = "Site visit notes, Blk 123 Ang Mo Kio\nThe estate officer agreed a follow-up visit.\n";

const note = (name = "site-visit.txt", content = NOTE) => new File([content], name, { type: "text/plain" });

/** A deferred reply: the test decides when an upload finishes, so its in-flight state can be seen. */
function deferred() {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  return { gate, release };
}

type Seen = { filename: string | null; body: string };

/** plg-api's upload, through the BFF: the recorded Upload named after the file sent, once `gate` opens. */
function uploadsApi(seen: Seen[] = [], gate: Promise<void> = Promise.resolve()) {
  let n = 0;
  return http.post("/api/uploads", async ({ request }) => {
    const filename = new URL(request.url).searchParams.get("filename");
    seen.push({ filename, body: await request.text() });
    await gate;
    n += 1;
    return HttpResponse.json(
      { ...uploadFixture(), upload_id: `upload-${n}`, filename, title: filename },
      { status: 201 },
    );
  });
}

function runsApi(bodies: unknown[], stream = fixture("upload")) {
  return http.post("/api/threads/:id/runs", async ({ request }) => {
    bodies.push(await request.json());
    return sseResponse(stream);
  });
}

function renderAsk(options: Parameters<typeof userEvent.setup>[0] = {}) {
  const user = userEvent.setup(options);
  const view = render(<AskScreen />);
  const picker = view.container.querySelector<HTMLInputElement>('input[type="file"]')!;
  return { user, picker, ...view };
}

const chips = () => screen.queryByRole("list", { name: "Attached files" });
const chip = (name: string) =>
  within(screen.getByRole("list", { name: "Attached files" }))
    .getAllByRole("listitem")
    .find((li) => li.textContent?.includes(name))!;

async function runFinished() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled(), { timeout: 5000 });
  await waitFor(() => expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("14 October 2026"), {
    timeout: 5000,
  });
}

beforeEach(() => {
  sessionStorage.clear();
  server.use(
    http.get("/api/threads", () => HttpResponse.json([])),
    http.get("/api/approvals", () => HttpResponse.json([])),
    http.post("/api/threads", () => HttpResponse.json({ thread_id: "t1" }, { status: 201 })),
  );
});

describe("Attaching files to a question (#103)", () => {
  it("uploads a file picked with the paperclip, shows its progress then Ready, and sends it with the question", async () => {
    const seen: Seen[] = [];
    const bodies: unknown[] = [];
    const { gate, release } = deferred();
    server.use(uploadsApi(seen, gate), runsApi(bodies));
    const { user, picker } = renderAsk();

    expect(screen.getByRole("button", { name: "Attach files" })).toBeVisible();
    expect(picker).toHaveAttribute("accept", ".pdf,.docx,.txt,.md,.eml,.png,.jpg,.jpeg");
    expect(picker).toHaveAttribute("multiple");
    await user.upload(picker, note());

    const item = chip("site-visit.txt");
    expect(item).toHaveTextContent(`site-visit.txt${new Blob([NOTE]).size} B`);
    expect(within(item).getByRole("progressbar", { name: "Uploading site-visit.txt" })).toBeInTheDocument();
    // Still uploading: the question can't go yet.
    await user.type(screen.getByLabelText("Your question"), QUESTION);
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(bodies).toEqual([]);

    release();
    expect(await within(item).findByText("Ready")).toBeInTheDocument();
    expect(within(item).queryByRole("progressbar")).not.toBeInTheDocument();
    expect(seen).toEqual([{ filename: "site-visit.txt", body: NOTE }]);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await runFinished();

    expect(bodies).toEqual([{ message: QUESTION, attachments: ["upload-1"] }]);
    expect(chips()).not.toBeInTheDocument();
    const sent = screen.getByRole("list", { name: "Files sent with your question" });
    expect(sent).toHaveTextContent("site-visit.txt");
  });

  it("removes a file before the question is sent, even while it is still uploading", async () => {
    const bodies: unknown[] = [];
    const { gate, release } = deferred();
    server.use(uploadsApi([], gate), runsApi(bodies));
    const { user, picker } = renderAsk();

    await user.upload(picker, [note("first.txt"), note("second.md")]);
    await user.click(screen.getByRole("button", { name: "Remove first.txt" }));

    expect(screen.queryByText("first.txt")).not.toBeInTheDocument();
    release();
    expect(await within(chip("second.md")).findByText("Ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove second.md" }));
    expect(chips()).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveFocus();

    await user.type(screen.getByLabelText("Your question"), QUESTION);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await runFinished();
    expect(bodies).toEqual([{ message: QUESTION }]);
    expect(screen.queryByRole("list", { name: "Files sent with your question" })).not.toBeInTheDocument();
  });

  it("shows plg-api's refusal on the file, which can then be removed", async () => {
    const refused = uploadRefusedFixture();
    server.use(http.post("/api/uploads", () => HttpResponse.json(refused.body, { status: refused.status })));
    const { user, picker } = renderAsk({ applyAccept: false });

    await user.upload(picker, new File(["PK"], "budget.xlsx"));

    const item = chip("budget.xlsx");
    expect(await within(item).findByRole("alert")).toHaveTextContent(refused.body.detail);
    expect(item).toHaveTextContent("Not attached");
    // A refused file never holds the question back.
    await user.type(screen.getByLabelText("Your question"), QUESTION);
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
    await user.click(within(item).getByRole("button", { name: "Remove budget.xlsx" }));
    expect(chips()).not.toBeInTheDocument();
  });

  it("flags an upload whose planted instructions were removed", async () => {
    const flag = {
      source: "document" as const, rules: ["override" as const], doc_id: "upload-1", title: "memo.txt",
      excerpt: "[Removed at ingestion: ...]",
    };
    server.use(http.post("/api/uploads", () => HttpResponse.json({ ...uploadFixture(), injection: flag }, { status: 201 })));
    const { user, picker } = renderAsk();

    await user.upload(picker, note("memo.txt"));

    const item = chip("memo.txt");
    expect(await within(item).findByText("Instructions removed")).toBeInTheDocument();
    expect(item).toHaveTextContent("Ready");
    const alert = screen.getAllByRole("alert").find((a) => /planted instructions were removed/.test(a.textContent ?? ""));
    expect(alert).toBeDefined(); // the injection alert, as soon as the file is attached
  });

  it("attaches at most 5 files to one question and says which were left out", async () => {
    const seen: Seen[] = [];
    server.use(uploadsApi(seen));
    const { user, picker } = renderAsk();

    await user.upload(picker, [1, 2, 3, 4, 5, 6].map((n) => note(`note-${n}.txt`)));

    expect(within(screen.getByRole("list", { name: "Attached files" })).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You can attach up to 5 files to one question. Not attached: note-6.txt.",
    );
    await waitFor(() => expect(seen).toHaveLength(5));
    expect(seen.map((s) => s.filename)).not.toContain("note-6.txt");
    // Removing one makes room again.
    await user.click(screen.getByRole("button", { name: "Remove note-1.txt" }));
    await user.upload(picker, note("note-6.txt"));
    expect(chip("note-6.txt")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("attaches files dropped onto the conversation, showing the drop target while they are dragged over", async () => {
    server.use(uploadsApi());
    renderAsk();
    const conversation = screen.getByRole("region", { name: "Conversation" });
    const dataTransfer = { types: ["Files"], files: [note("dropped.txt")], dropEffect: "none" };

    fireEvent.dragEnter(conversation, { dataTransfer });
    fireEvent.dragOver(conversation, { dataTransfer });
    expect(screen.getByText("Drop files to attach them to your question")).toBeVisible();
    fireEvent.drop(conversation, { dataTransfer });

    expect(screen.queryByText("Drop files to attach them to your question")).not.toBeInTheDocument();
    expect(await within(chip("dropped.txt")).findByText("Ready")).toBeInTheDocument();
  });

  it("ignores a drag that carries no files (the sidebar's conversations and groups)", () => {
    renderAsk();
    const conversation = screen.getByRole("region", { name: "Conversation" });
    const dataTransfer = { types: [DRAG_TYPE], files: [], getData: () => "t1" };

    fireEvent.dragEnter(conversation, { dataTransfer });
    fireEvent.dragOver(conversation, { dataTransfer });
    expect(screen.queryByText("Drop files to attach them to your question")).not.toBeInTheDocument();
    fireEvent.drop(conversation, { dataTransfer });

    expect(chips()).not.toBeInTheDocument();
  });
});

describe("A cited upload (#103)", () => {
  it("is marked 'Your upload' on its marker, in the sources panel and in the source viewer", async () => {
    const upload = documentFixture("upload");
    server.use(
      uploadsApi(),
      runsApi([]),
      http.get("/api/documents/:id", () => HttpResponse.json(upload.document)),
      http.get("/api/documents/:id/chunks/:chunk", () => HttpResponse.json(upload.location)),
    );
    const { user, picker } = renderAsk();
    await user.upload(picker, note());
    await within(chip("site-visit.txt")).findByText("Ready");
    await user.type(screen.getByLabelText("Your question"), QUESTION);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await runFinished();

    const marker = within(screen.getByRole("region", { name: "Answer" })).getByRole("button", {
      name: "[1] site-visit.txt, your upload",
    });
    expect(marker).toHaveTextContent("[1]");
    await user.click(marker);

    const panel = screen.getByRole("complementary", { name: "Sources" });
    const source = within(within(panel).getByRole("list", { name: "Sources" })).getByRole("listitem");
    expect(within(source).getByRole("heading", { level: 3 })).toHaveTextContent("[1] site-visit.txt Your upload");
    await user.click(within(source).getByRole("button", { name: "Open source" }));
    const viewer = await within(source).findByRole("region", { name: "Source: site-visit.txt" });
    expect(within(viewer).getByText("Your upload")).toBeInTheDocument();
    expect(viewer.querySelector("mark")).toHaveTextContent("agreed a follow-up visit with the tenant on 14 October 2026");
  });

  it("is not marked when the source is from the shared Library", async () => {
    server.use(runsApi([], fixture("answer")));
    const user = userEvent.setup();
    render(<AskScreen />);
    await user.type(screen.getByLabelText("Your question"), "When do we issue a letter of demand?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled(), { timeout: 5000 });

    const marker = await within(screen.getByRole("region", { name: "Answer" })).findByRole("button", { name: /^\[1\]/ });
    expect(marker).toHaveAccessibleName("[1] PLG-POL-003 Rental Arrears Management Policy (v2.0)");
    await user.click(marker);
    expect(within(screen.getByRole("complementary", { name: "Sources" })).queryByText("Your upload")).not.toBeInTheDocument();
  });
});
