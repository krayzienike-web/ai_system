import { describe, expect, it } from "vitest";

import { pct, perMonth, plural, points, rub, thousands } from "./format";

// Intl inserts non-breaking spaces between groups of digits.
const plain = (s: string) => s.replace(/\u00a0|\u202f/g, " ");

describe("money and numbers in words", () => {
  it("writes rubles the way people read them", () => {
    expect(plain(rub(900))).toBe("900 ₽");
    expect(plain(rub(38_000))).toBe("38 тыс ₽");
    expect(plain(rub(15_197))).toBe("15,2 тыс ₽");
    expect(plain(rub(1_250_000))).toBe("1,25 млн ₽");
    expect(plain(rub(-38_000))).toBe("-38 тыс ₽");
    expect(plain(perMonth(38_000))).toBe("38 тыс ₽ в месяц");
  });

  it("declines Russian plurals, including 11–14", () => {
    const forms: [string, string, string] = ["находка", "находки", "находок"];
    expect([1, 2, 5, 11, 12, 14, 21, 22, 25, 111, 101].map((n) => plural(n, forms))).toEqual([
      "1 находка",
      "2 находки",
      "5 находок",
      "11 находок",
      "12 находок",
      "14 находок",
      "21 находка",
      "22 находки",
      "25 находок",
      "111 находок",
      "101 находка",
    ]);
  });

  it("names percentage points", () => {
    expect(points(1)).toBe("1 пункт");
    expect(points(-2)).toBe("2 пункта");
    expect(points(1.54)).toBe("1,5 пункта");
    expect(pct(11.44)).toBe("11,4%");
    expect(thousands(128_400)).toBe("128");
    expect(thousands(12_840)).toBe("12,8");
  });
});
