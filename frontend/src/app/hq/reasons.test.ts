// Why a finding is rejected (code review 02.11.2026, front p. 8): the review form and the assistant's draft verdict
// use one list, and it is exactly the server's (`insights/review.py` RejectReason, `ai/precheck.py` Draft.reason).
import { describe, expect, it } from "vitest";

import { REASON_TITLE, REASONS } from "./reasons";

describe("reasons of a rejection", () => {
  it("are the server's four, each with its own words, «Другое» last", () => {
    expect(REASONS.map((r) => r.reason)).toEqual(["data", "logic", "false_alarm", "other"]);
    expect(new Set(REASONS.map((r) => r.title)).size).toBe(REASONS.length);
    expect(REASONS.every((r) => r.title.trim() && r.hint.trim())).toBe(true);
    expect(REASON_TITLE.false_alarm).toBe("Не проблема");
  });
});
