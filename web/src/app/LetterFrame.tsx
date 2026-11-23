import styles from "./ask.module.css";

const STYLE = ":root{color-scheme:light;background:#fff}body{font:15px/1.5 system-ui,sans-serif;margin:1rem;color:#111}p{margin:0 0 .75rem}mark{background:#fff3b0}";

/**
 * A letter as HTML from plg-api (every slot value escaped), shown in a sandboxed frame with no scripts, so nothing
 * in it can run. It keeps its own light look (a letter on paper) in the dark theme too.
 */
export function LetterFrame({ title, html }: { title: string; html: string }) {
  return <iframe title={title} sandbox="" srcDoc={`<style>${STYLE}</style>${html}`} className={styles.draftFrame} />;
}
