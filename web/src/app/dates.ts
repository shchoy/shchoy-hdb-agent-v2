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

const MOMENT = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore" });

/** A timestamp for display, in Singapore time: "13 Nov 2026, 12:26". */
export function when(iso: string): string {
  return MOMENT.format(new Date(iso));
}
