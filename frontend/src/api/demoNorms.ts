// Demo mode: the network's norms kept in the browser, with the same defaults and rules as the API
// (backend/app/norms). Only the HQ admin saves; everyone else reads.
import { ApiError } from "./client";
import type { Norms, WriteOffReason } from "./types";

const reason = (
  code: string,
  title: string,
  kind: WriteOffReason["kind"],
  synonyms: string[],
): WriteOffReason => ({
  code,
  title,
  kind,
  synonyms,
});

let norms: Norms = {
  food_cost_target_pct: "30.00",
  food_cost_by_category: {},
  loss_default_pct: "2.00",
  loss_by_category: {
    Овощи: "3.00",
    Зелень: "3.00",
    "Мясо и птица": "2.00",
    Рыба: "2.00",
    Сыры: "1.50",
    Молочные: "1.50",
    Бакалея: "1.00",
    Напитки: "1.00",
  },
  write_off_reasons: [
    reason("spoilage", "Порча, истек срок", "loss", [
      "порча",
      "истек срок",
      "просрочка",
      "испорчено",
      "срок годности",
    ]),
    reason("kitchen", "Брак при приготовлении", "loss", [
      "брак",
      "брак кухни",
      "пересол",
      "пригорело",
    ]),
    reason("breakage", "Бой, разлив", "loss", [
      "бой",
      "разлив",
      "разбито",
      "пролито",
    ]),
    reason("staff_meal", "Питание персонала", "planned", [
      "питание персонала",
      "персонал",
      "стафф",
      "staff",
    ]),
    reason("tasting", "Проработка, дегустация", "planned", [
      "проработка",
      "дегустация",
      "тестовое блюдо",
    ]),
    reason("compliment", "Комплимент гостю", "planned", [
      "комплимент",
      "угощение",
      "представительские",
    ]),
    reason("shortage", "Недостача по инвентаризации", "shortage", [
      "недостача",
      "инвентаризация",
      "пересорт",
    ]),
    reason("other", "Прочее", "loss", []),
  ],
  menu_categories: [
    "Горячее",
    "Десерты",
    "Закуски",
    "Паста",
    "Пицца",
    "Салаты",
  ],
  product_categories: [
    "Бакалея",
    "Заморозка",
    "Зелень",
    "Мясо и птица",
    "Молочные",
    "Овощи",
    "Рыба",
    "Сыры",
    "Хлеб",
  ],
};

const pct = (value: string, low: number, high: number, what: string) => {
  const n = Number(String(value).replace(",", "."));
  if (!Number.isFinite(n) || n < low || n > high)
    throw new ApiError(422, `${what}: от ${low} до ${high}%`);
  return n.toFixed(2);
};

export function demoNorms(init: RequestInit, isAdmin: boolean): Norms {
  if (init.method !== "PUT") return norms;
  if (!isAdmin)
    throw new ApiError(403, "Нормы меняет администратор управляющей компании");
  const body = JSON.parse(String(init.body)) as Norms;
  const codes = new Set<string>();
  for (const r of body.write_off_reasons) {
    if (!r.code || !r.title.trim() || codes.has(r.code))
      throw new ApiError(
        422,
        "У каждой причины списания нужны свой код и название",
      );
    codes.add(r.code);
  }
  const map = (
    m: Record<string, string>,
    low: number,
    high: number,
    what: string,
  ) =>
    Object.fromEntries(
      Object.entries(m).map(([k, v]) => [
        k,
        pct(v, low, high, `${what} «${k}»`),
      ]),
    );
  norms = {
    ...norms,
    food_cost_target_pct: pct(
      body.food_cost_target_pct,
      5,
      80,
      "Целевой фудкост",
    ),
    food_cost_by_category: map(body.food_cost_by_category, 5, 80, "Фудкост"),
    loss_default_pct: pct(body.loss_default_pct, 0, 30, "Допустимые потери"),
    loss_by_category: map(body.loss_by_category, 0, 30, "Потери"),
    write_off_reasons: [
      ...body.write_off_reasons.map((r) => ({
        ...r,
        title: r.title.trim(),
        synonyms: r.synonyms.map((s) => s.trim()).filter(Boolean),
      })),
      ...(codes.has("other") ? [] : [reason("other", "Прочее", "loss", [])]),
    ],
  };
  return norms;
}
