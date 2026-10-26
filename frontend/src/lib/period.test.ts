import { describe, expect, it } from "vitest";

import { customRangeError, iso, lastFullWeekEnd, resolvePeriod } from "./period";

// Thursday 23 October 2026, like the prototype's «today».
const today = new Date(2026, 9, 23);

describe("reporting period (same rules as backend/app/core/period.py)", () => {
  it("ends presets on the last full week, Monday to Sunday", () => {
    expect(iso(lastFullWeekEnd(today))).toBe("2026-10-18");
    const week = resolvePeriod({ preset: "week" }, today);
    expect([iso(week.from), iso(week.to)]).toEqual(["2026-10-12", "2026-10-18"]);
    const before = resolvePeriod({ preset: "prev_week" }, today);
    expect([iso(before.from), iso(before.to)]).toEqual(["2026-10-05", "2026-10-11"]);
    const four = resolvePeriod({ preset: "4w" }, today);
    expect([iso(four.from), iso(four.to)]).toEqual(["2026-09-21", "2026-10-18"]);
  });

  it("takes the last full calendar month", () => {
    const month = resolvePeriod({ preset: "month" }, today);
    expect([iso(month.from), iso(month.to)]).toEqual(["2026-09-01", "2026-09-30"]);
  });

  it("keeps at least two points on a trend and counts a custom range inclusively", () => {
    expect(resolvePeriod({ preset: "week" }, today).weeks).toBe(2);
    expect(resolvePeriod({ from: "2026-10-01", to: "2026-10-14" }, today).weeks).toBe(3);
  });

  it("rejects an incomplete custom range", () => {
    expect(customRangeError("", "2026-10-01", today)).toBe("Укажите обе даты");
    expect(customRangeError("2026-10-01", "2026-10-07", today)).toBeNull();
  });
});
