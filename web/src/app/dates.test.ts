import { describe, expect, it } from "vitest";
import { ago, dateOf } from "@/app/dates";

describe("ago", () => {
  const now = new Date("2026-11-24T10:00:00Z");
  it("says how long ago, in the largest whole unit, then the date after a week", () => {
    expect(ago("2026-11-24T09:59:40Z", now)).toBe("just now");
    expect(ago("2026-11-24T09:59:00Z", now)).toBe("1 min ago");
    expect(ago("2026-11-24T09:15:00Z", now)).toBe("45 min ago");
    expect(ago("2026-11-24T07:00:00Z", now)).toBe("3 h ago");
    expect(ago("2026-11-23T09:00:00Z", now)).toBe("1 day ago");
    expect(ago("2026-11-18T10:00:00Z", now)).toBe("6 days ago");
    expect(ago("2026-11-13T07:20:28Z", now)).toBe("on 13 Nov 2026");
  });

  it("treats a time a little in the future (clock skew) as just now", () => {
    expect(ago("2026-11-24T10:01:00Z", now)).toBe("just now");
  });
});

describe("dateOf", () => {
  it("gives a timestamp's day in Singapore", () => {
    expect(dateOf("2026-11-24T17:00:00Z")).toBe("25 Nov 2026");
  });
});
