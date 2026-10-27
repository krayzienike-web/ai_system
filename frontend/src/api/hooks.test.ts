// Code review 27.10.2026: the recalculation is not polled forever, and reference data is not refetched after actions.
import { describe, expect, it } from "vitest";

import { isStatic, runPollInterval } from "./hooks";
import type { LatestRun } from "./types";

const run = (status: LatestRun["status"], requested_at = "2026-10-27T10:00:00Z"): LatestRun => ({
  status,
  trigger: "upload",
  requested_at,
  finished_at: null,
  created: null,
  updated: null,
  removed: null,
});
const at = (iso: string) => Date.parse(iso);

describe("polling the latest recalculation", () => {
  it("polls while a run waits or goes on", () => {
    expect(runPollInterval(run("queued"), null, at("2026-10-27T10:01:00Z"))).toBe(3000);
    expect(runPollInterval(run("running"), null, at("2026-10-27T10:20:00Z"))).toBe(3000);
  });

  it("stops when the run is over, the request fails or the run hangs", () => {
    expect(runPollInterval(run("done"), null, at("2026-10-27T10:01:00Z"))).toBe(false);
    expect(runPollInterval(null, null, at("2026-10-27T10:01:00Z"))).toBe(false);
    expect(runPollInterval(run("running"), new Error("500"), at("2026-10-27T10:01:00Z"))).toBe(false);
    expect(runPollInterval(run("running"), null, at("2026-10-27T10:31:00Z"))).toBe(false);
  });
});

describe("what an action does not make stale", () => {
  it("keeps reference data, including the import templates", () => {
    expect(isStatic(["imports", "templates"])).toBe(true);
    expect(isStatic(["me"])).toBe(true);
    expect(isStatic(["imports"])).toBe(false);
    expect(isStatic(["findings", "board"])).toBe(false);
  });
});
