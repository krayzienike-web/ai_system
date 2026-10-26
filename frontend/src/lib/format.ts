const nf = new Intl.NumberFormat("ru-RU");

/** 38000 → "38 тыс ₽", 1250000 → "1,25 млн ₽", 900 → "900 ₽". */
export function rub(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн ₽`;
  if (abs >= 1_000) return `${(value / 1_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} тыс ₽`;
  return `${nf.format(value)} ₽`;
}

export const rubMonth = (value: number) => `${rub(value)}/мес`;

/** Russian plural: plural(4, ["проблема", "проблемы", "проблем"]) → "4 проблемы". */
export function plural(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const form = mod10 === 1 && mod100 !== 11 ? forms[0] : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? forms[1] : forms[2];
  return `${n} ${form}`;
}

/** "1 пункт", "2 пункта", "1,5 пункта": percentage-point difference in words. */
export function points(value: number): string {
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  const text = rounded.toLocaleString("ru-RU");
  return Number.isInteger(rounded) ? plural(rounded, ["пункт", "пункта", "пунктов"]) : `${text} пункта`;
}

export const num = (value: number) => nf.format(value);

export const pct = (value: number, digits = 1) =>
  `${value.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;

/** Money in words for people, not accountants: "теряем 38 тыс ₽ в месяц". */
export const perMonth = (value: number) => `${rub(value)} в месяц`;
export const lossWords = (value: number) => `теряем ${perMonth(value)}`;
export const gainWords = (value: number) => `можно заработать ${perMonth(value)}`;

/** Thousands with one decimal for big animated figures: 128 400 → "128,4". */
export const thousands = (value: number) =>
  (value / 1000).toLocaleString("ru-RU", { maximumFractionDigits: value >= 100_000 ? 0 : 1 });

/** Engine modules as people call them (docs/12-analytics-engine.md). */
export const MODULE_TITLE: Record<string, string> = {
  M1: "Потери по техкартам",
  M2: "Фудкост блюд",
  M3: "Закупочные цены",
  M4: "Инвентаризации",
  M5: "Списания",
  M6: "Риск дефицита",
  M7: "Качество данных",
};
