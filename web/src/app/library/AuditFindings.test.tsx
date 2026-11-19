import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { day, when } from "@/app/dates";
import { LibraryScreen } from "@/app/library/LibraryScreen";
import type { AuditReport } from "@/lib/events";
import { documentFixture } from "@/test/documents";
import { server } from "@/test/msw";
import { auditReportFixture, categoriesFixture } from "@/test/sse";

function serve(body: AuditReport | { detail: string }, status = 200) {
  server.use(
    http.get("/api/categories", () => HttpResponse.json(categoriesFixture())),
    http.get("/api/audit/reports/latest", () => HttpResponse.json(body, { status })),
  );
}

async function openAudit() {
  const user = userEvent.setup();
  render(<LibraryScreen />);
  await user.click(await screen.findByRole("tab", { name: "Audit findings" }));
  return user;
}

function section(name: RegExp) {
  return screen.getByRole("region", { name });
}

describe("Library audit findings", () => {
  it("switches between the categories and the audit findings", async () => {
    serve(auditReportFixture());
    const user = userEvent.setup();
    render(<LibraryScreen />);

    const categories = await screen.findByRole("tab", { name: "Categories" });
    expect(categories).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("list", { name: "Document categories" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Audit findings" }));
    expect(screen.getByRole("tab", { name: "Audit findings" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("region", { name: /^Conflicts/ })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Document categories" })).not.toBeInTheDocument();
  });

  it("shows when the audit ran and every section with its count", async () => {
    const report = auditReportFixture();
    serve(report);
    await openAudit();

    expect(
      await screen.findByText(`Audit of ${report.documents} documents on ${when(report.generated_at)}`),
    ).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual([
      `Conflicts (${report.conflicts!.length})`,
      `Near-duplicates (${report.duplicates!.length})`,
      `Stale documents (${report.stale!.length})`,
      `Reports using superseded definitions (${report.superseded_definitions!.length})`,
      `Data rule violations (${report.rule_violations!.length})`,
      `Gaps (${report.gaps!.length})`,
    ]);
  });

  it("shows both sides of a conflict with their quotes, the prevailing side and the expected resolution", async () => {
    const report = auditReportFixture();
    const lod = report.conflicts![0];
    serve(report);
    await openAudit();

    const conflicts = await screen.findByRole("region", { name: /^Conflicts/ });
    expect(within(conflicts).getAllByRole("article")).toHaveLength(report.conflicts!.length);
    const card = within(conflicts).getByRole("article", { name: lod.topic });
    const a = within(card).getByRole("group", { name: `Side A: ${lod.a.title}` });
    const b = within(card).getByRole("group", { name: `Side B: ${lod.b.title}` });
    expect(a).toHaveTextContent(lod.a.quote);
    expect(a).toHaveTextContent(`v${lod.a.version}`);
    expect(a).toHaveTextContent(lod.a.location!);
    expect(a).not.toHaveTextContent("Prevails");
    expect(b).toHaveTextContent(lod.b.quote);
    expect(b).toHaveTextContent("Prevails");
    expect(card).toHaveTextContent(`Expected resolution: ${lod.resolution}`);
  });

  it("shows a PLG Records side as a record that does not open", async () => {
    const report = auditReportFixture();
    const rent = report.conflicts!.find((c) => c.b.doc_id === null)!;
    serve(report);
    await openAudit();

    const card = within(await screen.findByRole("region", { name: /^Conflicts/ })).getByRole("article", {
      name: rent.topic,
    });
    const record = within(card).getByRole("group", { name: `Side B: ${rent.b.title}` });
    expect(record).toHaveTextContent("PLG Records");
    expect(record).toHaveTextContent(rent.b.quote);
    expect(within(record).queryByRole("button")).not.toBeInTheDocument();
    const doc = within(card).getByRole("group", { name: `Side A: ${rent.a.title}` });
    expect(doc).toHaveTextContent("Prevails");
    expect(within(doc).getByRole("button", { name: `Open ${rent.a.title}` })).toBeInTheDocument();
  });

  it("opens a document side with its quoted span highlighted", async () => {
    const report = auditReportFixture();
    const lod = report.conflicts![0];
    const fixture = documentFixture("docx"); // SP-888995, the policy side of the LOD conflict
    const block = fixture.document.blocks.findIndex((b) => b.text.includes(lod.b.quote));
    const chunkText = fixture.document.blocks[block].text;
    const start = chunkText.indexOf(lod.b.quote);
    const asked: string[] = [];
    serve(report);
    server.use(
      http.get("/api/documents/:id", ({ params }) => HttpResponse.json({ ...fixture.document, doc_id: params.id })),
      http.get("/api/documents/:id/chunks/:chunkId", ({ params, request }) => {
        const query = new URL(request.url).searchParams;
        asked.push(`${String(params.id)} ${String(params.chunkId)} ${query.get("start")}:${query.get("end")}`);
        const s = Number(query.get("start") ?? 0);
        const e = Number(query.get("end") ?? chunkText.length);
        return HttpResponse.json({
          doc_id: params.id,
          chunk_id: params.chunkId,
          location: lod.b.location,
          quote: chunkText.slice(s, e),
          page: null,
          highlights: [{ block, start: s, end: e }],
        });
      }),
    );
    const user = await openAudit();

    const card = within(await screen.findByRole("region", { name: /^Conflicts/ })).getByRole("article", {
      name: lod.topic,
    });
    const side = within(card).getByRole("group", { name: `Side B: ${lod.b.title}` });
    await user.click(within(side).getByRole("button", { name: `Open ${lod.b.title}` }));

    const viewer = await within(side).findByRole("region", { name: `Source: ${fixture.document.title}` });
    expect(viewer.querySelector("mark")?.textContent).toBe(lod.b.quote);
    expect(asked).toEqual([
      `${lod.b.doc_id} ${lod.b.chunk_id} null:null`,
      `${lod.b.doc_id} ${lod.b.chunk_id} ${start}:${start + lod.b.quote.length}`,
    ]);
  });

  it("lists near-duplicates with their kind, similarity and note, each document openable", async () => {
    const report = auditReportFixture();
    serve(report);
    await openAudit();

    const duplicates = await screen.findByRole("region", { name: /^Near-duplicates/ });
    const items = within(duplicates).getAllByRole("listitem");
    expect(items).toHaveLength(report.duplicates!.length);
    const [faq] = report.duplicates!;
    expect(items[0]).toHaveTextContent(faq.a.title);
    expect(items[0]).toHaveTextContent(faq.b.title);
    expect(items[0]).toHaveTextContent("Near-duplicate");
    expect(items[0]).toHaveTextContent(`${Math.round(faq.similarity * 100)}% similar`);
    expect(items[0]).toHaveTextContent(faq.note);
    expect(within(items[0]).getByRole("button", { name: `Open ${faq.b.title}` })).toBeInTheDocument();
    expect(items[1]).toHaveTextContent("Earlier version");
    expect(items[1]).toHaveTextContent("Superseded");
    expect(items[2]).toHaveTextContent("Same content");
  });

  it("lists stale documents, superseded definitions, rule violations and gaps", async () => {
    const report = auditReportFixture();
    serve(report);
    await openAudit();

    const [stale] = report.stale!;
    const staleItem = within(await screen.findByRole("region", { name: /^Stale documents/ })).getByRole("listitem");
    expect(staleItem).toHaveTextContent(stale.doc.title);
    expect(staleItem).toHaveTextContent(stale.quote);
    expect(staleItem).toHaveTextContent(`Relies on ${stale.relies_on}`);
    expect(staleItem).toHaveTextContent(`Current: ${stale.current_version} from ${day(stale.current_from!)}`);
    expect(staleItem).toHaveTextContent(stale.reason);

    const [qbr] = report.superseded_definitions!;
    const qbrItem = within(section(/^Reports using superseded definitions/)).getByRole("listitem");
    expect(qbrItem).toHaveTextContent(qbr.doc.title);
    expect(qbrItem).toHaveTextContent(qbr.quote);
    expect(qbrItem).toHaveTextContent(
      `Uses ${qbr.used_version}; current: ${qbr.current_version} from ${day(qbr.current_from!)}`,
    );
    expect(qbrItem).toHaveTextContent(qbr.explanation);
    expect(within(qbrItem).getByRole("button", { name: `Open ${qbr.doc.title}` })).toBeInTheDocument();

    const rules = within(section(/^Data rule violations/)).getAllByRole("listitem");
    expect(rules[0]).toHaveTextContent("Overlapping tenancies");
    expect(rules[1]).toHaveTextContent("Duplicate tenants");
    for (const [i, v] of report.rule_violations!.entries()) {
      for (const id of v.entity_ids) expect(rules[i]).toHaveTextContent(id);
      expect(rules[i]).toHaveTextContent(v.detail);
    }

    const gaps = within(section(/^Gaps/)).getAllByRole("listitem");
    const [parking] = report.gaps!;
    expect(gaps[0]).toHaveTextContent(parking.question);
    expect(gaps[0]).toHaveTextContent(`Asked ${parking.asked} times, last ${when(parking.last_asked)}`);
    expect(gaps[0]).toHaveTextContent("Not covered");
    expect(gaps[1]).toHaveTextContent("Asked once");
    expect(gaps[1]).toHaveTextContent("Low search score (0.12)");
  });

  it("says None found for an empty section", async () => {
    const report: AuditReport = { ...auditReportFixture(), stale: [], gaps: [] };
    serve(report);
    await openAudit();

    expect(await screen.findByRole("region", { name: /^Stale documents \(0\)/ })).toHaveTextContent("None found");
    expect(section(/^Gaps \(0\)/)).toHaveTextContent("None found");
    expect(section(/^Conflicts/)).not.toHaveTextContent("None found");
  });

  it("tells a policy owner to run plg audit when no audit has run yet", async () => {
    serve({ detail: "No corpus audit has run yet: run `plg audit`." }, 404);
    await openAudit();

    expect(await screen.findByRole("note")).toHaveTextContent(
      "No corpus audit has run yet. A policy owner runs plg audit to check the corpus.",
    );
    expect(screen.queryByRole("region", { name: /^Conflicts/ })).not.toBeInTheDocument();
  });

  it("shows an error when the audit report cannot be loaded", async () => {
    serve({ detail: "plg-api is unavailable" }, 502);
    await openAudit();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the audit findings.");
  });
});
