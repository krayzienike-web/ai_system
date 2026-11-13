import { ApiError } from "./client";
import { hasFactor } from "./demoUnits";
import snapshot from "./demo/snapshot.json";
// Data import in the standalone demo (no backend). A small copy of the server's rules
// (backend/app/imports): the header is found by column names, totals are skipped, the file type is
// recognised by its header. The server stays the source of truth; this only lets the prototype be clicked.
import type {
  AffectedFiles,
  CatalogOption,
  Freshness,
  ImportBatch,
  ImportTemplate,
  NameAlias,
  UnmatchedName,
} from "./types";

/** The import templates exactly as the server answers them (recorded with the rest of the snapshot): their
 * columns and synonyms are what the header is matched by, so a file the server takes the prototype takes too
 * (code review of stage 6.5, frontend p. 5). */
export const DEMO_TEMPLATES: ImportTemplate[] = (
  snapshot.users as unknown as Record<string, { answers: Record<string, unknown> }>
)["admin@demo.local"]?.answers["/imports/templates"] as ImportTemplate[] | undefined ?? [];

const batches: ImportBatch[] = [];
let seq = 0;

// The network's products (same as the synthetic network on the server) and names remembered in this session.
export const DEMO_PRODUCTS: CatalogOption[] = [
  "Сыр Моцарелла",
  "Сыр Пармезан",
  "Сыр Грана Падано",
  "Сливки 33%",
  "Мука пшеничная",
  "Томаты",
  "Куриное филе",
  "Говядина вырезка",
  "Лосось охлажденный",
  "Руккола",
  "Картофель фри замороженный",
  "Хлеб чиабатта",
  "Яйцо куриное",
  "Масло оливковое",
  "Паста спагетти",
  "Салат романо",
].map((name, i) => ({
  id: `P${String(i + 1).padStart(2, "0")}`,
  code: `P${String(i + 1).padStart(2, "0")}`,
  name,
}));
const remembered = new Map<
  string,
  {
    id: string;
    text: string;
    target: string;
    restaurant: string | null;
    batches: Set<string>;
    at: string;
  }
>();

const matchKey = (s: string) =>
  s
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}%]+/gu, " ")
    .trim();
const words = (s: string) =>
  matchKey(s)
    .split(" ")
    .filter((w) => w.length >= 4);
/** Shared words, abbreviations included — a simplified copy of backend/app/imports/matching.py. */
function similarity(a: string, b: string) {
  const wa = words(a);
  const wb = words(b);
  if (!wa.length || !wb.length) return 0;
  const hits = wa.filter((x) =>
    wb.some((y) => y.startsWith(x) || x.startsWith(y)),
  ).length;
  return (
    Math.round(
      ((hits / Math.min(wa.length, wb.length) +
        hits / Math.max(wa.length, wb.length)) /
        2) *
        1000,
    ) / 1000
  );
}

function unmatchedProducts(
  facts: string[][],
  column: number | undefined,
  firstRow: number,
): UnmatchedName[] {
  if (column === undefined) return [];
  const known = new Set(DEMO_PRODUCTS.map((p) => matchKey(p.name)));
  const found = new Map<string, UnmatchedName>();
  facts.forEach((r, i) => {
    const name = (r[column] ?? "").trim();
    const key = matchKey(name);
    if (!name || known.has(key) || remembered.has(key)) return;
    const item = found.get(key) ?? {
      kind: "product",
      code: null,
      name,
      key,
      rows: [],
      rows_count: 0,
      candidates: DEMO_PRODUCTS.map((p) => ({
        id: p.id,
        name: p.name,
        score: similarity(name, p.name),
      }))
        .filter((c) => c.score >= 0.3)
        .sort((x, y) => y.score - x.score)
        .slice(0, 3),
    };
    item.rows.push(firstRow + i);
    item.rows_count += 1;
    found.set(key, item);
  });
  return [...found.values()];
}

const norm = (s: string) =>
  s.replace(/\s+/g, " ").trim().replace(/:$/, "").toLowerCase();
const iso = (ddmmyyyy: string) => {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})/.exec(ddmmyyyy.trim());
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
};

function mapHeader(cells: string[], t: ImportTemplate): Record<string, number> {
  const found: Record<string, number> = {};
  cells.forEach((cell, i) => {
    const name = norm(cell);
    const c = t.columns.find(
      (x) => norm(x.title) === name || x.synonyms.includes(name),
    );
    if (c && !(c.title in found)) found[c.title] = i;
  });
  return found;
}

const complete = (found: Record<string, number>, t: ImportTemplate) =>
  t.columns.every((c) => !c.required || c.title in found) &&
  t.one_of.every((g) => g.some((n) => n in found));

async function readCsv(file: File): Promise<string[][]> {
  const buffer = await file.arrayBuffer();
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    text = new TextDecoder("windows-1251").decode(buffer);
  }
  const delimiter = [";", ",", "\t"].sort(
    (a, b) => text.split(b).length - text.split(a).length,
  )[0]!;
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1); // byte order mark
  return text.split(/\r?\n/).map((line) => line.split(delimiter));
}

function failed(
  base: Omit<ImportBatch, "status" | "errors">,
  message: string,
): ImportBatch {
  return {
    ...base,
    status: "failed",
    errors: [{ row: null, column: null, message }],
  };
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
    unmatched: [],
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
      warnings: [
        { row: null, column: null, message: "пропущено строк итогов: 1" },
      ],
      column_map: {
        Дата: "1",
        "Код блюда": "2",
        Блюдо: "3",
        Количество: "4",
        Выручка: "5",
        Скидка: "6",
      },
    };
  } else {
    const rows = await readCsv(file);
    const scope = restaurantId ? "restaurant" : "network";
    const candidates = DEMO_TEMPLATES.filter((t) =>
      asked ? t.name === asked : t.scope === scope,
    );
    let best: {
      t: ImportTemplate;
      header: number;
      found: Record<string, number>;
    } | null = null;
    for (const t of candidates) {
      const header = rows
        .slice(0, 30)
        .findIndex((r) => complete(mapHeader(r, t), t));
      if (header < 0) continue;
      const found = mapHeader(rows[header]!, t);
      if (!best || Object.keys(found).length > Object.keys(best.found).length)
        best = { t, header, found };
    }
    if (!best) {
      batch = failed(
        base,
        `Не узнали файл. Ожидали один из: ${candidates.map((t) => t.title.toLowerCase()).join(", ")}. Проверьте строку заголовков`,
      );
    } else {
      const data = rows
        .slice(best.header + 1)
        .filter((r) => r.some((c) => c.trim()));
      const totals = data.filter((r) =>
        /^\s*(итого|всего)/i.test(r.find((c) => c.trim()) ?? ""),
      );
      const facts = data.filter((r) => !totals.includes(r));
      const dateCol = best.found["Дата"];
      const days =
        dateCol === undefined
          ? []
          : facts
              .map((r) => iso(r[dateCol] ?? ""))
              .filter((d): d is string => !!d)
              .sort();
      const unmatched =
        best.t.name === "sales"
          ? []
          : unmatchedProducts(facts, best.found["Товар"], best.header + 2);
      const unmatchedRows = unmatched.reduce((n, u) => n + u.rows_count, 0);
      batch = {
        ...base,
        template: best.t.name,
        status: !facts.length
          ? "failed"
          : unmatched.length
            ? "needs_matching"
            : "validated",
        unmatched,
        rows_total: facts.length,
        rows_valid: facts.length - unmatchedRows,
        period_from: days[0] ?? null,
        period_to: days.at(-1) ?? null,
        errors: facts.length
          ? []
          : [
              {
                row: null,
                column: null,
                message: "В файле нет строк с данными",
              },
            ],
        warnings: totals.length
          ? [
              {
                row: null,
                column: null,
                message: `пропущено строк итогов: ${totals.length}`,
              },
            ]
          : [],
        column_map: Object.fromEntries(
          Object.entries(best.found).map(([k, v]) => [k, String(v + 1)]),
        ),
      };
    }
  }
  batches.unshift(batch);
  return batch;
}

/** Whose a batch or a remembered name is: `undefined` when there is no such thing. */
export const demoBatchRestaurant = (id: string) =>
  batches.find((b) => b.id === id)?.restaurant_id;
export const demoAliasRestaurant = (id: string) =>
  [...remembered.values()].find((a) => a.id === id)?.restaurant;

export function demoMatch(id: string, body: string): ImportBatch {
  const batch = batches.find((b) => b.id === id);
  if (!batch) throw new ApiError(404, "Загрузка не найдена");
  const { matches } = JSON.parse(body) as {
    matches: { key: string; target_id: string }[];
  };
  for (const m of matches) {
    const text = batch.unmatched.find((u) => u.key === m.key)?.name ?? m.key;
    remembered.set(m.key, {
      id: `alias-${m.key}`,
      text,
      target: m.target_id,
      restaurant: batch.restaurant_id,
      batches: new Set([batch.id]),
      at: new Date().toISOString(),
    });
  }
  batch.rows_valid = batch.rows_total;
  batch.unmatched = [];
  batch.status = "validated";
  return { ...batch };
}

export function demoAliases(restaurantId: string | null): NameAlias[] {
  return [...remembered.values()]
    .filter(
      (a) => !restaurantId || !a.restaurant || a.restaurant === restaurantId,
    )
    .map((a) => ({
      id: a.id,
      kind: "product",
      source_text: a.text,
      target_id: a.target,
      target_name:
        DEMO_PRODUCTS.find((p) => p.id === a.target)?.name ?? a.target,
      restaurant_id: a.restaurant,
      created_at: a.at,
      files: [...a.batches].filter(
        (id) => batches.find((b) => b.id === id)?.status === "published",
      ).length,
    }));
}

export function demoAliasEdit(id: string, init: RequestInit): AffectedFiles {
  const entry = [...remembered.entries()].find(([, a]) => a.id === id);
  if (!entry) throw new ApiError(404, "Соответствие не найдено");
  const [key, alias] = entry;
  const affected = batches
    .filter((b) => alias.batches.has(b.id) && b.status === "published")
    .map((b) => ({
      id: b.id,
      filename: b.filename,
      template: b.template,
      restaurant_id: b.restaurant_id,
    }));
  if (init.method === "DELETE") remembered.delete(key);
  else
    alias.target = (
      JSON.parse(String(init.body)) as { target_id: string }
    ).target_id;
  return { affected_files: affected };
}

export function demoBatchAction(
  id: string,
  action: "publish" | "rollback" | "reprocess",
): ImportBatch {
  const batch = batches.find((b) => b.id === id);
  if (!batch) throw new ApiError(404, "Загрузка не найдена");
  if (action === "reprocess") return { ...batch };
  batch.status = action === "publish" ? "published" : "rolled_back";
  if (action === "publish") batch.published_at = new Date().toISOString();
  return { ...batch };
}

/** «Проверить снова» (Q35) on a file recorded from the server: the units that now have a factor stop being
 * errors; once none is left the file waits for «Загрузить», as on the server (imports/service.py `recheck`).
 * A file that passes moves into this session's files, so «Загрузить» works on it. */
export function demoRecheck(recorded: ImportBatch[], id: string): ImportBatch {
  const batch = recorded.find((b) => b.id === id) ?? batches.find((b) => b.id === id);
  if (!batch) throw new ApiError(404, "Загрузка не найдена");
  if (batch.status !== "failed") throw new ApiError(422, "Проверить заново можно только файл с ошибками");
  const fixes = batch.unit_fixes ?? [];
  const fixed = fixes.filter((f) => hasFactor(f.product_id, f.unit));
  const left = fixes.filter((f) => !fixed.includes(f));
  const errors = batch.errors.filter(
    (e) =>
      !fixed.some((f) => e.message.includes(`«${f.unit_text}»`) && e.message.includes(`«${f.product_name}»`)),
  );
  const rows = fixed.reduce((n, f) => n + f.rows, 0);
  const checked: ImportBatch = {
    ...batch,
    errors,
    unit_fixes: left,
    rows_valid: batch.rows_valid + rows,
    status: errors.length ? "failed" : "validated",
  };
  const own = batches.indexOf(batch);
  if (own >= 0) batches.splice(own, 1);
  const at = recorded.indexOf(batch);
  if (at >= 0) recorded.splice(at, 1);
  // A file that passed is this session's to load; one with errors left stays where it was listed.
  if (checked.status === "validated" || own >= 0) batches.unshift(checked);
  else recorded.splice(at, 0, checked);
  return { ...checked };
}

export const demoBatches = (restaurantId: string | null) =>
  batches
    .filter((b) => !restaurantId || b.restaurant_id === restaurantId)
    .map((b) => ({ ...b }));

/** The server's freshness as recorded, moved forward by files published in this prototype session. */
export function demoFreshness(recorded: Freshness[]): Freshness[] {
  return recorded.map((f) => {
    const published = batches.find(
      (b) =>
        b.restaurant_id === f.restaurant_id &&
        b.template === f.template &&
        b.status === "published" &&
        b.period_to &&
        (!f.last_date || b.period_to > f.last_date),
    );
    return published ? { ...f, last_date: published.period_to, status: "good" } : f;
  });
}
