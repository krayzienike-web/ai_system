// Units of the exports in the prototype (Q35): the same rules and words as the server (catalog/units.py).
import { describe, expect, it } from "vitest";

import { showFactor } from "../app/UnitFactors";
import { ApiError } from "./client";
import { demoRequest } from "./demo";
import { factorProblem, unitKey } from "./demoUnits";
import type { CatalogOption, UnitFactor, UnitFactorSaved } from "./types";

const ADMIN = "admin@demo.local";
const DIRECTOR = "director1@demo.local";

const call = (path: string, init: RequestInit, token: string) => demoRequest(path, init, token);
const put = (token: string, body: object) =>
  call("/settings/units", { method: "PUT", body: JSON.stringify(body) }, token) as UnitFactorSaved;
const fails = (fn: () => unknown): [number, string] | null => {
  try {
    fn();
  } catch (e) {
    if (e instanceof ApiError) return [e.status, e.message];
    throw e;
  }
  return null;
};

describe("units of the exports in the prototype", () => {
  it("lets the HQ admin add, change and delete a factor; a director only reads", () => {
    const products = call("/catalog/product", {}, ADMIN) as CatalogOption[];
    const cheese = products.find((p) => p.name.includes("Моцарелла")) ?? products[0]!;
    expect(fails(() => put(DIRECTOR, { product_id: cheese.id, unit_text: "упак", factor: "2,5" }))?.[0]).toBe(403);

    const saved = put(ADMIN, { product_id: cheese.id, unit_text: "Упак.", factor: "2,5" });
    expect(saved.factor.unit).toBe("упак");
    expect(saved.factor.factor).toBe("2.5");
    const again = put(ADMIN, { product_id: cheese.id, unit_text: "УПАК", factor: "3" });
    expect(again.factor.id).toBe(saved.factor.id); // one factor per product and unit
    const listed = call("/settings/units", {}, DIRECTOR) as UnitFactor[];
    expect(listed.filter((f) => f.product_id === cheese.id).map((f) => f.factor)).toEqual(["3"]);

    expect(call(`/settings/units/${saved.factor.id}`, { method: "DELETE" }, ADMIN)).toEqual({ affected_files: [] });
    expect(fails(() => call(`/settings/units/${saved.factor.id}`, { method: "DELETE" }, ADMIN))?.[0]).toBe(404);
  });

  it("refuses what the server refuses, in its words", () => {
    expect(factorProblem("0")).toBe("Коэффициент должен быть больше нуля");
    expect(factorProblem("-1")).toBe("Коэффициент должен быть больше нуля");
    expect(factorProblem("много")).toBe("Коэффициент — число, например 2,5");
    expect(factorProblem("20000")).toBe("Коэффициент больше 10 000 — проверьте, та ли единица");
    expect(factorProblem("0,0000001")).toBe("Коэффициент — не больше шести знаков после запятой");
    expect(factorProblem("2,5")).toBeNull();
    // As the server's Decimal (frontend review of stage 10, p. 9)
    expect(factorProblem("2,5000000")).toBeNull();
    expect(factorProblem(".5")).toBeNull();
    expect(factorProblem("1e3")).toBeNull();
    expect(unitKey("Бут. 0,5")).toBe("бут 0 5");
    expect(showFactor("2.500000")).toBe("2,5");
    const kg = (call("/catalog/product", {}, ADMIN) as CatalogOption[]).find((p) => (p.base_unit ?? "kg") === "kg")!;
    expect(fails(() => put(ADMIN, { product_id: kg.id, unit_text: "г", factor: "0,001" }))).toEqual([
      422,
      "«г» и так переводится в кг — коэффициент не нужен",
    ]);
    expect(fails(() => put(ADMIN, { product_id: kg.id, unit_text: "g", factor: "0,001" }))?.[0]).toBe(422);
    expect(fails(() => put(ADMIN, { product_id: kg.id, unit_text: "у".repeat(41), factor: "1" }))).toEqual([
      422,
      "Единица — не длиннее 40 символов",
    ]);
  });
});
