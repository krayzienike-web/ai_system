import { describe, expect, it } from "vitest";

import type { EngineParam } from "../../api/types";
import { rangeError } from "./EngineParams";

const p = { key: "M3_OVERPAY", low: "1", high: "50" } as EngineParam;

describe("engine parameter input", () => {
  it("accepts numbers in range, with a comma or a dot", () => {
    expect(rangeError(p, "5")).toBeNull();
    expect(rangeError(p, "2,5")).toBeNull();
    expect(rangeError(p, "50")).toBeNull();
  });
  it("explains what is wrong", () => {
    expect(rangeError(p, "")).toBe("нужно число");
    expect(rangeError(p, "пять")).toBe("нужно число");
    expect(rangeError(p, "0,5")).toBe("от 1 до 50");
    expect(rangeError(p, "51")).toBe("от 1 до 50");
  });
});
