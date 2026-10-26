import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, RotateCcw, UploadCloud, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { type DragEvent, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { useBatchAction, useFreshness, useImports, useImportTemplates, useRestaurants, useUploadImport } from "../api/hooks";
import type { BatchStatus, Freshness, ImportBatch } from "../api/types";
import { Button, Card, cx, EASE, PageTitle, Pill, QuestionBlock, Reveal, type Tone } from "../ds/primitives";
import { plural } from "../lib/format";
import { useViewer } from "../lib/useViewer";

const NETWORK = "network";
const KINDS = [
  { template: "sales", title: "Продажи", system: "r_keeper" },
  { template: "receipts", title: "Закупки", system: "1С:ERP" },
  { template: "write_offs", title: "Списания", system: "iiko" },
  { template: "inventory_counts", title: "Инвентаризации", system: "iiko" },
] as const;

const STATUS: Record<BatchStatus, { label: string; tone: Tone }> = {
  validated: { label: "Проверен, ждет загрузки", tone: "info" },
  failed: { label: "Есть ошибки", tone: "loss" },
  published: { label: "Загружен", tone: "gain" },
  rolled_back: { label: "Отменен", tone: "neutral" },
};

/** "2026-10-18" → "18.10". */
const ddmm = (iso: string | null) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}` : "—");
const period = (b: ImportBatch) => (b.period_from ? (b.period_from === b.period_to ? ddmm(b.period_from) : `${ddmm(b.period_from)}–${ddmm(b.period_to)}`) : "");

function useNames() {
  const { data: restaurants = [] } = useRestaurants();
  const { data: templates = [] } = useImportTemplates();
  return {
    restaurants,
    restaurant: (id: string | null) => (id ? (restaurants.find((r) => r.id === id)?.name ?? "Ресторан") : "Вся сеть (справочник)"),
    template: (name: string) => templates.find((t) => t.name === name)?.title ?? name,
    templates,
  };
}

// ------------------------------------------------------------------ upload

function Report({ batch, onAgain }: { batch: ImportBatch; onAgain: () => void }) {
  const names = useNames();
  const publish = useBatchAction("publish");
  const rollback = useBatchAction("rollback");
  const [shown, setShown] = useState(8);
  const current = rollback.data ?? publish.data ?? batch;
  const error = (publish.error ?? rollback.error) as Error | null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid h-11 w-11 place-items-center rounded-[12px] bg-brand-soft text-brand-strong">
          <FileSpreadsheet size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{current.filename}</div>
          <div className="text-sm text-ink-3">{plural(current.rows_total, ["строка", "строки", "строк"])} с данными</div>
        </div>
        <Pill tone={STATUS[current.status].tone}>{STATUS[current.status].label}</Pill>
      </div>

      {current.status !== "failed" || current.rows_total > 0 ? (
        <div className="rounded-[14px] bg-paper p-4">
          <div className="font-medium">Мы поняли файл так:</div>
          <dl className="mt-2 grid gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-ink-3">Что это</dt>
              <dd className="font-medium">{names.template(current.template)}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Куда</dt>
              <dd className="font-medium">{names.restaurant(current.restaurant_id)}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Период</dt>
              <dd className="font-medium">{period(current) || "справочник"}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Строк без ошибок</dt>
              <dd className="font-medium">
                {current.rows_valid} из {current.rows_total}
              </dd>
            </div>
          </dl>
          {Object.keys(current.column_map).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
              {Object.entries(current.column_map).map(([title, n]) => (
                <span key={title} className="rounded-full border border-line bg-surface px-2.5 py-1 text-ink-2">
                  колонка {n} → <span className="font-medium text-ink">{title}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {current.errors.length > 0 && (
        <div className="rounded-[14px] border border-loss-icon/40 bg-loss-soft/50 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium text-loss">
            <XCircle size={17} /> Файл не загружен: {plural(current.errors.length, ["ошибка", "ошибки", "ошибок"])}
          </div>
          <p className="mt-1 text-ink-2">Ни одна строка не попала в систему — исправьте файл и загрузите его снова.</p>
          <ul className="mt-3 space-y-1.5">
            {current.errors.slice(0, shown).map((e, i) => (
              <li key={i} className="flex gap-2">
                <span className="num shrink-0 font-medium text-ink">{e.row ? `Строка ${e.row}` : "Файл"}</span>
                <span className="text-ink-2">
                  {e.column && <span className="text-ink-3">{e.column}: </span>}
                  {e.message}
                </span>
              </li>
            ))}
          </ul>
          {current.errors.length > shown && (
            <button type="button" onClick={() => setShown((n) => n + 20)} className="mt-2 text-brand-strong hover:underline">
              Показать еще {Math.min(20, current.errors.length - shown)}
            </button>
          )}
        </div>
      )}

      {current.warnings.length > 0 && (
        <ul className="space-y-1.5 text-sm">
          {current.warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-ink-2">
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
              <span>
                {w.row && <span className="font-medium text-ink">Строка {w.row}: </span>}
                {w.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      {error && <p className="text-sm text-loss">{error instanceof ApiError ? error.message : "Не получилось, попробуйте еще раз"}</p>}

      <div className="flex flex-wrap items-center gap-2">
        {current.status === "validated" && (
          <Button variant="primary" disabled={publish.isPending} onClick={() => publish.mutate(current.id)}>
            {publish.isPending ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />} Загрузить в систему
          </Button>
        )}
        {current.status === "published" && (
          <motion.div
            initial={{ scale: 0.97, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="flex w-full flex-wrap items-center gap-3 rounded-[14px] bg-gain-soft p-4 text-sm text-gain"
          >
            <CheckCircle2 size={18} />
            <span className="flex-1">
              Загружено {plural(current.rows_valid, ["строка", "строки", "строк"])}
              {current.period_from && ` за ${period(current)}`}. Если за эти дни данные уже были, они заменены — дублей не будет.
            </span>
            {current.restaurant_id && (
              <Button size="sm" variant="ghost" disabled={rollback.isPending} onClick={() => rollback.mutate(current.id)}>
                <RotateCcw size={14} /> Отменить загрузку
              </Button>
            )}
          </motion.div>
        )}
        {current.status === "rolled_back" && <p className="text-sm text-ink-2">Загрузка отменена: строки этого файла удалены.</p>}
        <Button variant="ghost" onClick={onAgain}>
          {current.status === "failed" ? "Загрузить исправленный файл" : "Загрузить другой файл"}
        </Button>
      </div>
    </div>
  );
}

function Upload() {
  const viewer = useViewer();
  const names = useNames();
  const upload = useUploadImport();
  const input = useRef<HTMLInputElement>(null);
  const [target, setTarget] = useState<string>("");
  const [template, setTemplate] = useState("");
  const [dragging, setDragging] = useState(false);
  if (!viewer) return null;

  const restaurants = names.restaurants;
  const where = target || (viewer.isHq ? (restaurants[0]?.id ?? "") : (restaurants[0]?.id ?? ""));
  const isNetwork = where === NETWORK;
  const kinds = names.templates.filter((t) => t.scope === (isNetwork ? "network" : "restaurant"));
  const send = (file: File | undefined) => {
    if (!file) return;
    upload.mutate({ file, restaurantId: isNetwork ? null : where, template: template || null });
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    send(e.dataTransfer.files[0]);
  };

  return (
    <Card className="overflow-hidden">
      <AnimatePresence mode="wait">
        <motion.div
          key={upload.data ? "report" : "drop"}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: EASE }}
          className="p-6"
        >
          {upload.data ? (
            <Report key={upload.data.id} batch={upload.data} onAgain={() => upload.reset()} />
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3">
                <label className="text-sm">
                  <span className="mb-1 block text-ink-3">Куда загружаем</span>
                  <select
                    value={where}
                    onChange={(e) => {
                      setTarget(e.target.value);
                      setTemplate("");
                    }}
                    disabled={!viewer.isHq}
                    className="h-10 min-w-[220px] rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-brand disabled:bg-paper"
                  >
                    {restaurants.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                    {viewer.isAdmin && <option value={NETWORK}>Вся сеть — справочники и техкарты</option>}
                  </select>
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ink-3">Что в файле</span>
                  <select
                    value={template}
                    onChange={(e) => setTemplate(e.target.value)}
                    className="h-10 min-w-[220px] rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-brand"
                  >
                    <option value="">Определить по файлу</option>
                    {kinds.map((t) => (
                      <option key={t.name} value={t.name}>
                        {t.title}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <button
                type="button"
                onClick={() => input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                disabled={upload.isPending}
                className={cx(
                  "flex w-full flex-col items-center gap-3 rounded-[16px] border-2 border-dashed px-6 py-10 text-center transition",
                  dragging ? "border-brand bg-brand-soft" : "border-line-strong bg-paper hover:border-brand",
                )}
              >
                {upload.isPending ? <Loader2 size={32} className="animate-spin text-brand" /> : <UploadCloud size={32} className="text-brand" />}
                <span className="font-display text-lg font-semibold">{upload.isPending ? "Проверяем файл…" : "Перетащите выгрузку сюда или выберите файл"}</span>
                <span className="max-w-md text-sm text-ink-2">
                  Excel или CSV из r_keeper, iiko или 1С. Приводить файл к шаблону не нужно: мы найдем заголовки, пропустим итоги и
                  покажем, как поняли файл, до загрузки.
                </span>
              </button>
              <input
                ref={input}
                type="file"
                accept=".csv,.xlsx,.xls,text/csv"
                className="sr-only"
                aria-label="Файл выгрузки"
                onChange={(e) => {
                  send(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              {upload.error && (
                <p className="text-sm text-loss">{upload.error instanceof ApiError ? upload.error.message : "Не получилось загрузить файл"}</p>
              )}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </Card>
  );
}

// ------------------------------------------------------------------ freshness

const FRESH_TONE: Record<Freshness["status"], Tone> = { good: "gain", stale: "warn", missing: "loss" };

function FreshnessBlock() {
  const names = useNames();
  const { data: rows = [], isLoading } = useFreshness();
  if (isLoading) return null;
  const restaurants = [...new Set(rows.map((r) => r.restaurant_id))];
  const problems = rows.filter((r) => r.status !== "good");
  // One phrase per kind of data, so the answer stays short for 3 restaurants and for 100.
  const summary = KINDS.flatMap((k) => {
    const bad = problems.filter((p) => p.template === k.template);
    if (!bad.length) return [];
    if (restaurants.length === 1) {
      const p = bad[0]!;
      return [`${k.title.toLowerCase()} ${p.last_date ? `только по ${ddmm(p.last_date)}` : "не загружены"}`];
    }
    return [`${k.title.toLowerCase()} — в ${bad.length} из ${restaurants.length} ресторанов`];
  });
  const cell = (rid: string, template: string) => rows.find((r) => r.restaurant_id === rid && r.template === template);

  return (
    <QuestionBlock
      question="Все ли данные на месте?"
      answer={
        summary.length
          ? `Не все. Нет данных за последнюю полную неделю: ${summary.join("; ")}.`
          : "Да, данные за последнюю неделю загружены везде."
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr className="border-b border-line">
              <th className="py-2 pr-4 font-medium">Ресторан</th>
              {KINDS.map((k) => (
                <th key={k.template} className="py-2 pr-4 font-medium">
                  {k.title} <span className="font-normal">· {k.system}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {restaurants.map((rid) => (
              <tr key={rid} className="border-b border-line last:border-0">
                <td className="py-2.5 pr-4 font-medium">{names.restaurant(rid)}</td>
                {KINDS.map((k) => {
                  const c = cell(rid, k.template);
                  return (
                    <td key={k.template} className="py-2.5 pr-4">
                      {c && <Pill tone={FRESH_TONE[c.status]}>{c.last_date ? `по ${ddmm(c.last_date)}` : "нет данных"}</Pill>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-3">Зеленый — есть данные за последнюю полную неделю; инвентаризации проходят раз в 1–3 месяца.</p>
    </QuestionBlock>
  );
}

// ------------------------------------------------------------------ history

function History() {
  const names = useNames();
  const { data: batches = [] } = useImports();
  const rollback = useBatchAction("rollback");
  const [shown, setShown] = useState(10);
  if (!batches.length) return null;
  return (
    <QuestionBlock question="Что загружали?" answer="Сначала последние. Загрузку данных ресторана можно отменить — удалятся ровно ее строки.">
      <ul className="divide-y divide-line">
        {batches.slice(0, shown).map((b) => (
          <li key={b.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-sm">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{b.filename}</span>
              <span className="block text-ink-3">
                {names.template(b.template)} · {names.restaurant(b.restaurant_id)}
                {period(b) && ` · ${period(b)}`} · {plural(b.rows_valid, ["строка", "строки", "строк"])}
              </span>
            </span>
            <Pill tone={STATUS[b.status].tone}>{STATUS[b.status].label}</Pill>
            {b.status === "published" && b.restaurant_id && (
              <Button size="sm" variant="ghost" disabled={rollback.isPending} onClick={() => rollback.mutate(b.id)}>
                <RotateCcw size={14} /> Отменить
              </Button>
            )}
          </li>
        ))}
      </ul>
      {batches.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + 20)} className="mt-2 text-sm font-medium text-brand-strong hover:underline">
          Показать еще {Math.min(20, batches.length - shown)}
        </button>
      )}
    </QuestionBlock>
  );
}

export function DataPage() {
  const viewer = useViewer();
  if (!viewer) return null;
  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <PageTitle title="Данные" subtitle="Загрузка выгрузок и свежесть данных: откуда система берет цифры" />
      <Reveal>
        <Upload />
      </Reveal>
      <Reveal index={1}>
        <FreshnessBlock />
      </Reveal>
      <Reveal index={2}>
        <History />
      </Reveal>
    </div>
  );
}
