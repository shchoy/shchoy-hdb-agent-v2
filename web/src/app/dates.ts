const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** An ISO date for display: "2026-08-01" → "1 Aug 2026". */
export function day(iso: string): string {
  return DATE.format(new Date(`${iso}T00:00:00Z`));
}

/** When something applied: "1 Aug 2026 to 31 Dec 2026", "from 1 Aug 2026", "until ...", or `undated`. */
export function period(from: string | null, to: string | null, undated: string): string {
  if (from && to) return `${day(from)} to ${day(to)}`;
  if (from) return `from ${day(from)}`;
  if (to) return `until ${day(to)}`;
  return undated;
}

const SGT_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" });

/** The day of a timestamp, in Singapore: "2026-11-24T17:00:00Z" → "25 Nov 2026". */
export function dateOf(iso: string): string {
  return SGT_DATE.format(new Date(iso));
}

const MOMENT = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore" });

/** A timestamp for display, in Singapore time: "13 Nov 2026, 12:26". */
export function when(iso: string): string {
  return MOMENT.format(new Date(iso));
}

/** How long ago, for a list: "just now", "45 min ago", "3 h ago", "2 days ago", then the date ("on 13 Nov 2026"). */
export function ago(iso: string, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return `on ${DATE.format(new Date(iso))}`;
}
