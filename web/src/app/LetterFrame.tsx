import styles from "./ask.module.css";

const STYLE = "body{font:15px/1.5 system-ui,sans-serif;margin:1rem;color:#111}p{margin:0 0 .75rem}mark{background:#fff3b0}";

/**
 * A letter as HTML from plg-api (every slot value escaped), shown in a sandboxed frame with no scripts, so nothing
 * in it can run.
 */
export function LetterFrame({ title, html }: { title: string; html: string }) {
  return <iframe title={title} sandbox="" srcDoc={`<style>${STYLE}</style>${html}`} className={styles.draftFrame} />;
}
