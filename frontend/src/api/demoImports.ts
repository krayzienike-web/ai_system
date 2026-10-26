// Data import in the standalone demo (no backend). A small copy of the server's rules
// (backend/app/imports): the header is found by column names, totals are skipped, the file type is
// recognised by its header. The server stays the source of truth; this only lets the prototype be clicked.
import { FRESHNESS, RESTAURANTS } from "../mock/data";
import type { Freshness, ImportBatch, ImportTemplate } from "./types";

const col = (title: string, required = false, ...synonyms: string[]) => ({ title, required, synonyms });
const PRODUCT = [col("Код товара", false, "артикул"), col("Товар", false, "номенклатура", "наименование товара")];

export const DEMO_TEMPLATES: ImportTemplate[] = [
  { name: "restaurants", title: "Рестораны", scope: "network", one_of: [], columns: [col("Код", true), col("Название", true, "ресторан"), col("Город")] },
  { name: "products", title: "Номенклатура", scope: "network", one_of: [], columns: [col("Код", true), col("Наименование", true, "товар"), col("Категория"), col("Базовая ед.", true, "ед. изм."), col("Срок годности, дней")] },
  { name: "suppliers", title: "Поставщики", scope: "network", one_of: [], columns: [col("Код", true), col("Название", true, "поставщик"), col("ИНН")] },
  { name: "menu_items", title: "Блюда", scope: "network", one_of: [], columns: [col("Код", true), col("Блюдо", true, "наименование"), col("Категория"), col("Цена")] },
  { name: "recipes", title: "Технологические карты (ТТК)", scope: "network", one_of: [["Код товара", "Товар"]], columns: [col("Код блюда", true), ...PRODUCT, col("Брутто", true, "кол-во брутто"), col("Ед. изм."), col("Действует с", true)] },
  { name: "sales", title: "Продажи", scope: "restaurant", one_of: [["Код блюда", "Блюдо"]], columns: [col("Дата", true), col("Код блюда", false, "код"), col("Блюдо", false), col("Количество", true, "кол-во"), col("Выручка", true, "сумма"), col("Скидка")] },
  { name: "receipts", title: "Приходы (накладные)", scope: "restaurant", one_of: [["Код товара", "Товар"]], columns: [col("Дата", true), col("№ накладной"), col("Код поставщика"), col("Поставщик", false, "контрагент"), ...PRODUCT, col("Количество", true, "кол-во"), col("Ед. изм."), col("Цена"), col("Сумма", true, "сумма с ндс"), col("НДС")] },
  { name: "write_offs", title: "Списания", scope: "restaurant", one_of: [["Код товара", "Товар"]], columns: [col("Дата", true), ...PRODUCT, col("Количество", true, "кол-во"), col("Ед. изм."), col("Причина", false, "статья списания")] },
  { name: "inventory_counts", title: "Инвентаризации", scope: "restaurant", one_of: [["Код товара", "Товар"]], columns: [col("Дата", true), ...PRODUCT, col("Учетный остаток"), col("Фактический остаток", true, "факт"), col("Ед. изм.")] },
];

const batches: ImportBatch[] = [];
let seq = 0;

const norm = (s: string) => s.replace(/\s+/g, " ").trim().replace(/:$/, "").toLowerCase();
const iso = (ddmmyyyy: string) => {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})/.exec(ddmmyyyy.trim());
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
};

function mapHeader(cells: string[], t: ImportTemplate): Record<string, number> {
  const found: Record<string, number> = {};
  cells.forEach((cell, i) => {
    const name = norm(cell);
    const c = t.columns.find((x) => norm(x.title) === name || x.synonyms.includes(name));
    if (c && !(c.title in found)) found[c.title] = i;
  });
  return found;
}

const complete = (found: Record<string, number>, t: ImportTemplate) =>
  t.columns.every((c) => !c.required || c.title in found) && t.one_of.every((g) => g.some((n) => n in found));

async function readCsv(file: File): Promise<string[][]> {
  const buffer = await file.arrayBuffer();
  let text = new TextDecoder("utf-8").decode(buffer);
  if (text.includes("\uFFFD")) text = new TextDecoder("windows-1251").decode(buffer);
  const delimiter = [";", ",", "\t"].sort((a, b) => text.split(b).length - text.split(a).length)[0]!;
  return text.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.split(delimiter));
}

function failed(base: Omit<ImportBatch, "status" | "errors">, message: string): ImportBatch {
  return { ...base, status: "failed", errors: [{ row: null, column: null, message }] };
}

export async function demoUpload(form: FormData): Promise<ImportBatch> {
  const file = form.get("file") as File;
  const restaurantId = (form.get("restaurant_id") as string | null) || null;
  const asked = form.get("template") as string | null;
  seq += 1;
  const base = {
    id: `demo-${seq}`,
    restaurant_id: restaurantId,
    template: asked ?? "sales",
    filename: file.name,
    rows_total: 0,
    rows_valid: 0,
    period_from: null,
    period_to: null,
    warnings: [],
    column_map: {},
    created_at: new Date().toISOString(),
    published_at: null,
  };
  let batch: ImportBatch;
  if (/\.xlsx?$/i.test(file.name)) {
    // Excel is parsed by the server; the prototype shows what a typical sales export looks like.
    batch = {
      ...base,
      template: asked ?? "sales",
      status: "validated",
      rows_total: 2050,
      rows_valid: 2050,
      period_from: "2026-04-20",
      period_to: "2026-10-18",
      errors: [],
      warnings: [{ row: null, column: null, message: "пропущено строк итогов: 1" }],
      column_map: { Дата: "1", "Код блюда": "2", Блюдо: "3", Количество: "4", Выручка: "5", Скидка: "6" },
    };
  } else {
    const rows = await readCsv(file);
    const scope = restaurantId ? "restaurant" : "network";
    const candidates = DEMO_TEMPLATES.filter((t) => (asked ? t.name === asked : t.scope === scope));
    let best: { t: ImportTemplate; header: number; found: Record<string, number> } | null = null;
    for (const t of candidates) {
      const header = rows.slice(0, 30).findIndex((r) => complete(mapHeader(r, t), t));
      if (header < 0) continue;
      const found = mapHeader(rows[header]!, t);
      if (!best || Object.keys(found).length > Object.keys(best.found).length) best = { t, header, found };
    }
    if (!best) {
      batch = failed(base, `Не узнали файл. Ожидали один из: ${candidates.map((t) => t.title.toLowerCase()).join(", ")}. Проверьте строку заголовков`);
    } else {
      const data = rows.slice(best.header + 1).filter((r) => r.some((c) => c.trim()));
      const totals = data.filter((r) => /^\s*(итого|всего)/i.test(r.find((c) => c.trim()) ?? ""));
      const facts = data.filter((r) => !totals.includes(r));
      const dateCol = best.found["Дата"];
      const days = dateCol === undefined ? [] : facts.map((r) => iso(r[dateCol] ?? "")).filter((d): d is string => !!d).sort();
      batch = {
        ...base,
        template: best.t.name,
        status: facts.length ? "validated" : "failed",
        rows_total: facts.length,
        rows_valid: facts.length,
        period_from: days[0] ?? null,
        period_to: days.at(-1) ?? null,
        errors: facts.length ? [] : [{ row: null, column: null, message: "В файле нет строк с данными" }],
        warnings: totals.length ? [{ row: null, column: null, message: `пропущено строк итогов: ${totals.length}` }] : [],
        column_map: Object.fromEntries(Object.entries(best.found).map(([k, v]) => [k, String(v + 1)])),
      };
    }
  }
  batches.unshift(batch);
  return batch;
}

export function demoBatchAction(id: string, action: "publish" | "rollback"): ImportBatch {
  const batch = batches.find((b) => b.id === id);
  if (!batch) throw new Error("Загрузка не найдена");
  batch.status = action === "publish" ? "published" : "rolled_back";
  if (action === "publish") batch.published_at = new Date().toISOString();
  return { ...batch };
}

export const demoBatches = (restaurantId: string | null) =>
  batches.filter((b) => !restaurantId || b.restaurant_id === restaurantId).map((b) => ({ ...b }));

const SOURCE_OF: Record<string, "r_keeper" | "iiko" | "erp"> = {
  sales: "r_keeper",
  receipts: "erp",
  write_offs: "iiko",
  inventory_counts: "iiko",
};

export function demoFreshness(restaurantId: string | null): Freshness[] {
  return RESTAURANTS.filter((r) => !restaurantId || r.code === restaurantId).flatMap((r) =>
    Object.entries(SOURCE_OF).map(([template, source]) => {
      const mock = FRESHNESS.find((f) => f.restaurantId === r.code && f.source === source)!;
      const published = batches.find((b) => b.restaurant_id === r.code && b.template === template && b.status === "published" && b.period_to);
      const last = template === "inventory_counts" ? "2026-10-01" : `2026-${mock.lastDate.slice(3, 5)}-${mock.lastDate.slice(0, 2)}`;
      const date = published?.period_to && published.period_to > last ? published.period_to : last;
      return { restaurant_id: r.code, template, last_date: date, status: template === "inventory_counts" || date >= "2026-10-12" ? "good" : "stale" };
    }),
  );
}
