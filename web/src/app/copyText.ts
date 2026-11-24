import type { Cited } from "./SourcesPanel";

const FENCE = /^\s*(```|~~~)/;

/** One line of prose without its markdown: headings, emphasis, inline code and links become their text. */
function plainLine(line: string): string {
  return line
    .replace(/^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!?\[([^\]]*)\]\(([^)\s]+)\)/g, "$1 ($2)")
    .replace(/(\*\*|__)(?=\S)(.+?)(?<=\S)\1/g, "$2")
    .replace(/(^|[^*\w])\*(?=\S)(.+?)(?<=\S)\*(?![*\w])/g, "$1$2");
}

/** A source as one line: `[n] title (vX), location`; the version only when the title leaves it out. */
function sourceLine(c: Cited): string {
  const version = c.version && !c.title.includes(c.version) ? ` (v${c.version})` : "";
  return `[${c.index}] ${c.title}${version}, ${c.location}`;
}

/**
 * An answer as plain text for the clipboard: the markdown dropped (code kept as written), the `[n]` markers kept,
 * then a "Sources" list naming what each marker refers to, once per number, in number order.
 */
export function answerAsText(markdown: string, citations: Cited[]): string {
  let fenced = false;
  const lines: string[] = [];
  for (const line of markdown.split("\n")) {
    if (FENCE.test(line)) {
      fenced = !fenced;
      continue;
    }
    lines.push(fenced ? line : plainLine(line));
  }
  const text = lines.join("\n").trim();
  const byIndex = new Map<number, Cited>();
  for (const c of citations) if (!byIndex.has(c.index)) byIndex.set(c.index, c);
  if (byIndex.size === 0) return text;
  const sources = [...byIndex.values()].sort((a, b) => a.index - b.index).map(sourceLine);
  return `${text}\n\nSources\n${sources.join("\n")}`;
}
