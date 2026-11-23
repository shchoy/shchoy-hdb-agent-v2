import type { DraftEvent } from "@/lib/events";
import styles from "./ask.module.css";
import { Card } from "./Card";
import { LetterFrame } from "./LetterFrame";

/**
 * A letter drafted from an approved template: its preview, the slots still to fill, personal data to remove,
 * and the DOCX download. Nothing is sent. The preview is HTML from plg-api (every slot value escaped), shown
 * in a sandboxed frame with no scripts, so nothing in it can run.
 */
export function DraftPreview({ draft }: { draft: DraftEvent }) {
  return (
    <Card heading="Draft preview">
      <p>
        {draft.template_title} ({draft.template_id} v{draft.template_version}). Nothing has been sent.
      </p>
      {draft.unfilled.length > 0 && (
        <div className={styles.draftNote}>
          <h4>Still to fill</h4>
          <ul aria-label="Unfilled slots">
            {draft.unfilled.map((u) => (
              <li key={u.slot}>
                <code>{u.slot}</code>: {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {draft.pii.length > 0 && (
        <div role="alert" className={styles.alert}>
          <h4>Personal data to remove</h4>
          <ul aria-label="Personal data flags">
            {draft.pii.map((p, i) => (
              <li key={i}>
                <code>{p.slot}</code>: {p.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      <LetterFrame title={`Preview of ${draft.template_title}`} html={draft.html} />
      <a href={`/api/drafts/${encodeURIComponent(draft.draft_id)}/file`} download>
        Download DOCX
      </a>
    </Card>
  );
}
