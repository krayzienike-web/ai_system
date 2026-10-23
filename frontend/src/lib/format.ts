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

export const num = (value: number) => nf.format(value);

export const pct = (value: number, digits = 1) =>
  `${value.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
