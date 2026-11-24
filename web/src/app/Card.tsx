import { useId, type ElementType, type ReactNode } from "react";
import styles from "./card.module.css";

/** Danger is HDB red: alerts, overdue markers and problems only. Success is green; neutral grey; warning amber. */
export type Tone = "neutral" | "success" | "warning" | "danger";

/** A status badge: always words, so the tone is never the only signal. */
export function Badge({
  tone = "neutral",
  as: Tag = "span",
  children,
}: {
  tone?: Tone;
  as?: ElementType;
  children: ReactNode;
}) {
  return (
    <Tag className={styles.badge} data-tone={tone}>
      {children}
    </Tag>
  );
}

const HEADINGS = { 2: "h2", 3: "h3", 4: "h4" } as const;

type CardProps = {
  /** Names the card (a region); without one the card needs a role, e.g. an alert. */
  heading?: ReactNode;
  /** 2 for an item that is a top-level section of its screen (a Library category). */
  level?: 2 | 3 | 4;
  /** Status badges shown beside the heading. */
  badges?: ReactNode;
  /** "danger" for alerts only: a red frame. */
  tone?: "neutral" | "danger";
  role?: "alert";
  /** A self-contained item in a list (an approval, a decision, a memory) is an article; a result inside an answer a section. */
  as?: "section" | "article";
  children: ReactNode;
};

/**
 * The shared card: a result inside an answer, or an item in a screen's list (as an article): a header (heading + status badges) over a body. Nested
 * <details> (evidence, more) and tables (in TableScroll) get the card's look.
 */
export function Card({ heading, level = 3, badges, tone = "neutral", role, as: Tag = "section", children }: CardProps) {
  const id = useId();
  const Heading = HEADINGS[level];
  const header = (heading !== undefined || badges) && (
    <div className={styles.header}>
      {heading !== undefined && (
        <Heading id={id} className={styles.heading}>
          {heading}
        </Heading>
      )}
      {badges && <div className={styles.badges}>{badges}</div>}
    </div>
  );
  const body = <div className={styles.body}>{children}</div>;
  if (role || heading === undefined) {
    return (
      <div role={role} className={styles.card} data-tone={tone}>
        {header}
        {body}
      </div>
    );
  }
  return (
    <Tag aria-labelledby={id} className={styles.card} data-tone={tone}>
      {header}
      {body}
    </Tag>
  );
}

/** A table that scrolls sideways on a narrow screen; focusable so keyboard users can scroll it too. */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className={styles.tableScroll}>
      {children}
    </div>
  );
}

/** A list of cards on a screen (an inbox, a trail, memories). */
export const cardListClass = styles.list;
/** The card's table style (use inside TableScroll). */
export const tableClass = styles.table;
/** A definition list of label/value pairs in the card's two-column layout. */
export const fieldsClass = styles.fields;
