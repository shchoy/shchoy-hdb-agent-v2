import { describe, expect, it } from "vitest";
import { answerAsText } from "./copyText";
import type { Cited } from "./SourcesPanel";

function cited(index: number, title: string, version: string | null, location: string): Cited {
  return {
    index,
    title,
    version,
    location,
    doc_id: `D${index}`,
    chunk_id: `D${index}#0`,
    quote: "q",
    span: { start: 0, end: 1 },
  } as Cited;
}

describe("answerAsText", () => {
  it("drops the markdown, keeps the [n] markers and lists the sources they refer to", () => {
    const text = answerAsText(
      "Under **POL-003 v2.0**, a letter of demand is issued once arrears reach 60 days [1].",
      [cited(1, "PLG-POL-003 Rental Arrears Management Policy (v2.0)", "2.0", "4.5 Letter of Demand")],
    );

    expect(text).toBe(
      "Under POL-003 v2.0, a letter of demand is issued once arrears reach 60 days [1].\n\n" +
        "Sources\n" +
        "[1] PLG-POL-003 Rental Arrears Management Policy (v2.0), 4.5 Letter of Demand",
    );
  });

  it("names a version the title leaves out, lists each source once, in marker order", () => {
    const text = answerAsText("A [2] and B [1] and A again [2].", [
      cited(2, "SOP-014 Arrears follow-up", "3", "Step 2"),
      cited(1, "Circular 7", null, "Page 1"),
      cited(2, "SOP-014 Arrears follow-up", "3", "Step 2"),
    ]);

    expect(text.split("Sources\n")[1]).toBe("[1] Circular 7, Page 1\n[2] SOP-014 Arrears follow-up (v3), Step 2");
  });

  it("turns headings, emphasis, inline code, links and code fences into plain text", () => {
    const text = answerAsText(
      [
        "## Arrears",
        "*Only* `plg:Arrears_v1` counts; see [the SOP](https://example.test/sop).",
        "",
        "```sql",
        "SELECT **x** FROM t",
        "```",
        "- snake_case_id stays",
      ].join("\n"),
      [],
    );

    expect(text).toBe(
      [
        "Arrears",
        "Only plg:Arrears_v1 counts; see the SOP (https://example.test/sop).",
        "",
        "SELECT **x** FROM t",
        "- snake_case_id stays",
      ].join("\n"),
    );
  });
});
