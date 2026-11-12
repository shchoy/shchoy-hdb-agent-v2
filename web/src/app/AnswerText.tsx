import { useId } from "react";
import ReactMarkdown from "react-markdown";

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

/** An answer's markdown; a multi-part answer is shown as one labelled section per part. */
export function AnswerText({ markdown }: { markdown: string }) {
  const id = useId();
  return (
    <>
      {sections(markdown).map((part, i) =>
        part.title === null ? (
          <ReactMarkdown key={i} skipHtml>
            {part.body}
          </ReactMarkdown>
        ) : (
          <section key={i} aria-labelledby={`${id}-${i}`}>
            <h3 id={`${id}-${i}`}>{part.title}</h3>
            <ReactMarkdown skipHtml>{part.body}</ReactMarkdown>
          </section>
        ),
      )}
    </>
  );
}
