const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** An ISO date for display: "2026-08-01" → "1 Aug 2026". */
export function day(iso: string): string {
  return DATE.format(new Date(`${iso}T00:00:00Z`));
}
