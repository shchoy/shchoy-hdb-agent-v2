import { createContext, useContext, useId, type ComponentProps } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { markerLabel, type Cited } from "./SourcesPanel";
import styles from "./ask.module.css";

type Part = { title: string | null; body: string };

/**
 * Splits an answer at its `## ` headings: merge writes one section per part of a multi-part question.
 * Lines inside fenced code blocks are never headings.
 */
function sections(markdown: string): Part[] {
  const parts: Part[] = [{ title: null, body: "" }];
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) fenced = !fenced;
    const heading = fenced ? null : /^##\s+(.+?)\s*#*\s*$/.exec(line);
    if (heading) parts.push({ title: heading[1], body: "" });
    else parts[parts.length - 1].body += line + "\n";
  }
  return parts.filter((p) => p.title !== null || p.body.trim() !== "");
}

/** The bit of a HAST tree the citation plugin walks. */
type HastNode = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

const MARKER = /\[(\d+)\]/g;

/** Text never searched for markers: code stays as written. */
const LITERAL = new Set(["code", "pre"]);

/**
 * A rehype plugin: each `[n]` in the answer's text becomes a `<button data-citation="n">` (rendered by
 * `CitationMarker`). The markdown skips raw HTML, so the only buttons in an answer are these.
 */
function rehypeCitations() {
  return (tree: HastNode) => splitMarkers(tree);
}

function splitMarkers(node: HastNode) {
  if (!node.children || (node.tagName && LITERAL.has(node.tagName))) return;
  node.children = node.children.flatMap((child) => {
    if (child.type !== "text" || !child.value) {
      splitMarkers(child);
      return [child];
    }
    const out: HastNode[] = [];
    let at = 0;
    for (const match of child.value.matchAll(MARKER)) {
      if (match.index > at) out.push({ type: "text", value: child.value.slice(at, match.index) });
      out.push({
        type: "element",
        tagName: "button",
        properties: { dataCitation: match[1] },
        children: [{ type: "text", value: match[0] }],
      });
      at = match.index + match[0].length;
    }
    if (at === 0) return [child];
    if (at < child.value.length) out.push({ type: "text", value: child.value.slice(at) });
    return out;
  });
}

/** What activating an `[n]` marker does: open the sources panel at source n; `opener` gets focus back on close. */
export type OnCite = (index: number, opener: HTMLButtonElement) => void;

/** The answer's citations by marker number, and what activating a marker does. */
const Markers = createContext<{ byIndex: Map<number, Cited>; onCite?: OnCite }>({ byIndex: new Map() });

/**
 * One `[n]` marker. A module-level component (not one made per render), so a marker keeps its DOM node while the
 * answer re-renders: focus can go back to it when the panel closes.
 */
function CitationMarker({ children, ...props }: ComponentProps<"button">) {
  const { byIndex, onCite } = useContext(Markers);
  const n = Number((props as Record<string, unknown>)["data-citation"]);
  const citation = byIndex.get(n);
  if (!citation || !onCite) return <>{children}</>;
  return (
    <button
      type="button"
      className={styles.citation}
      aria-label={markerLabel(citation)}
      data-upload={citation.upload ? "" : undefined}
      onClick={(event) => onCite(n, event.currentTarget)}
    >
      {children}
      {citation.upload && (
        <span className={styles.uploadMark} aria-hidden="true">
          upload
        </span>
      )}
    </button>
  );
}

const COMPONENTS: Components = { button: CitationMarker };
const REHYPE = [rehypeCitations];

/**
 * An answer's markdown; a multi-part answer is shown as one labelled section per part. With `citations`, each `[n]`
 * of a cited source is a button (named by the source) that opens the sources panel at it; a marker of no known
 * source stays text.
 */
export function AnswerText({
  markdown,
  citations = [],
  onCite,
}: {
  markdown: string;
  citations?: Cited[];
  onCite?: OnCite;
}) {
  const id = useId();
  const markers = { byIndex: new Map(citations.map((c) => [c.index, c])), onCite };
  const markdownOf = (body: string) => (
    <ReactMarkdown skipHtml rehypePlugins={REHYPE} components={COMPONENTS}>
      {body}
    </ReactMarkdown>
  );
  return (
    <Markers.Provider value={markers}>
      {sections(markdown).map((part, i) =>
        part.title === null ? (
          <div key={i}>{markdownOf(part.body)}</div>
        ) : (
          <section key={i} aria-labelledby={`${id}-${i}`}>
            <h3 id={`${id}-${i}`}>{part.title}</h3>
            {markdownOf(part.body)}
          </section>
        ),
      )}
    </Markers.Provider>
  );
}
