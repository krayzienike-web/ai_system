// Demo mode: the network's units of the exports (Q35) kept in the browser, by the API's rules
// (backend/app/catalog/units.py). Only the HQ admin saves; nothing in the demo network was converted by
// them, so a change names no files to re-process.
import { ApiError } from "./client";
import type { AffectedFiles, CatalogOption, UnitFactor, UnitFactorSaved } from "./types";

const STANDARD: Record<string, string> = {
  кг: "kg", kg: "kg", г: "kg", g: "kg", гр: "kg", килограмм: "kg", грамм: "kg",
  л: "l", l: "l", мл: "l", ml: "l", литр: "l",
  шт: "pcs", pcs: "pcs", штук: "pcs",
};
const TITLES: Record<string, string> = { kg: "кг", l: "л", pcs: "шт" };

let factors: UnitFactor[] = [];

/** As the server's `normalize`: case, «ё», punctuation and spaces do not make two units different. */
export const unitKey = (text: string) =>
  text.toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}_%]+/gu, " ").trim();

/** The server's checks of a factor (TC-IMP-41), in its words. */
export function factorProblem(text: string): string | null {
  const cleaned = text.replace(",", ".").trim();
  // As the server's Decimal(): «2,5», «.5», «1e3» are numbers; trailing zeros are not decimals (review, p. 9)
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(cleaned)) return "Коэффициент — число, например 2,5";
  const value = Number(cleaned);
  if (!(value > 0)) return "Коэффициент должен быть больше нуля";
  if (value > 10_000) return "Коэффициент больше 10 000 — проверьте, та ли единица";
  if (Math.round(value * 1e6) / 1e6 !== value) return "Коэффициент — не больше шести знаков после запятой";
  return null;
}

/** As the server's `unit_of`: the standard unit by case and a trailing dot only. */
const standardOf = (text: string) => STANDARD[text.trim().toLowerCase().replace(/\.+$/, "")];

export function demoUnits(
  path: string,
  init: RequestInit,
  admin: boolean,
  products: CatalogOption[],
): UnitFactor[] | UnitFactorSaved | AffectedFiles {
  const method = init.method ?? "GET";
  if (method === "GET") return factors;
  if (!admin) throw new ApiError(403, "Единицы в выгрузках задает администратор управляющей компании");
  const id = /^\/settings\/units\/([^/]+)$/.exec(path)?.[1];
  if (method === "DELETE") {
    if (!factors.some((f) => f.id === id)) throw new ApiError(404, "Коэффициент не найден");
    factors = factors.filter((f) => f.id !== id);
    return { affected_files: [] };
  }
  const body = JSON.parse(String(init.body)) as { product_id: string; unit_text: string; factor: string };
  const product = products.find((p) => p.id === body.product_id);
  if (!product) throw new ApiError(404, "Товар не найден в справочнике");
  const text = body.unit_text.trim();
  const unit = unitKey(text);
  if (!unit) throw new ApiError(422, "Укажите единицу, как она написана в выгрузке, например «упак»");
  if (text.length > 40) throw new ApiError(422, "Единица — не длиннее 40 символов");
  const base = product.base_unit ?? "kg"; // a snapshot older than the base units in the catalog: kg
  if (standardOf(text) === base)
    throw new ApiError(422, `«${text}» и так переводится в ${TITLES[base]} — коэффициент не нужен`);
  const problem = factorProblem(body.factor);
  if (problem) throw new ApiError(422, problem);
  const factor = String(Number(body.factor.replace(",", ".")));
  const old = factors.find((f) => f.product_id === product.id && f.unit === unit);
  const saved: UnitFactor = {
    id: old?.id ?? `unit-${factors.length + 1}-${Date.now()}`,
    product_id: product.id,
    product_code: product.code,
    product_name: product.name,
    base_unit: base,
    unit,
    unit_text: text,
    factor,
    files: 0,
    created_at: old?.created_at ?? new Date().toISOString(),
  };
  factors = [...factors.filter((f) => f !== old), saved].sort((a, b) =>
    a.product_name.localeCompare(b.product_name, "ru") || a.unit.localeCompare(b.unit, "ru"),
  );
  return { factor: saved, affected_files: [] };
}
