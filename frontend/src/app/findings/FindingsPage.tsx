import { Link } from "@tanstack/react-router";
import { ChevronRight, RotateCcw } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { cx, EASE, EmptyState, PageTitle, Reveal } from "../../ds/primitives";
import { PROCESS_ICON } from "../../ds/viz";
import { plural, rub } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { FINDINGS, RESTAURANTS } from "../../mock/data";
import { CheckedFindingsSection } from "./EngineFindings";
import { PROCESSES, processTitle, restaurantByCode } from "../../mock/selectors";
import type { Finding, FindingKind, ProcessKey } from "../../mock/types";
import { useWork, type WorkStage } from "../counts";
import { StagePill } from "./parts";

type Stage = "all" | WorkStage;

const STAGES: { key: Stage; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "new", label: "Новые" },
  { key: "doing", label: "Делаем" },
  { key: "checking", label: "Проверяем" },
  { key: "done", label: "Есть результат" },
];

const LINE_TONE = { loss: "text-loss", gain: "text-gain", info: "text-info", warn: "text-warn" } as const;

const KIND = {
  problem: { title: "Где теряем", hint: "перерасход, переплаты, списания", text: "text-loss", bar: "bg-loss-icon", soft: "bg-loss-soft text-loss", ring: "ring-loss-icon" },
  opportunity: { title: "Где можно заработать", hint: "цены меню, поставщики, запасы", text: "text-gain", bar: "bg-gain-icon", soft: "bg-gain-soft text-gain", ring: "ring-gain-icon" },
} as const;

const select =
  "h-10 rounded-[10px] border border-line-strong bg-surface px-3 text-sm text-ink outline-none transition hover:border-ink-3 focus:border-brand";

/** One finding as a row: money first (with a bar to compare), then what and where. */
function Row({ f, max, showRestaurant, index }: { f: Finding; max: number; showRestaurant: boolean; index: number }) {
  const work = useWork()(f);
  const Icon = PROCESS_ICON[f.process];
  const k = KIND[f.kind];
  const restaurant = f.restaurantId ? restaurantByCode(f.restaurantId) : null;
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25, ease: EASE, delay: Math.min(index, 10) * 0.025 }}
    >
      <Link
        to="/findings/$findingId"
        params={{ findingId: f.id }}
        className="group grid grid-cols-[96px_1fr_auto] items-center gap-4 rounded-[14px] px-4 py-3.5 transition-colors hover:bg-paper sm:grid-cols-[132px_1fr_auto]"
      >
        <span className="min-w-0">
          {f.effectRubMonth !== null ? (
            <>
              <span className={cx("num block font-display text-[19px] leading-none font-semibold", k.text)}>{rub(f.effectRubMonth)}</span>
              <span className="mt-1 block text-[11px] text-ink-3">в месяц</span>
              <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-ink/5">
                <motion.span
                  className={cx("block h-full rounded-full", k.bar)}
                  initial={{ width: 0 }}
                  animate={{ width: `${(f.effectRubMonth / max) * 100}%` }}
                  transition={{ duration: 0.5, ease: EASE, delay: 0.1 + Math.min(index, 10) * 0.025 }}
                />
              </span>
            </>
          ) : (
            <span className="block text-xs leading-tight text-ink-3">{f.effectNote ?? "без оценки"}</span>
          )}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium text-ink group-hover:underline">{f.title}</span>
          <span className="mt-0.5 block truncate text-sm text-ink-3">{f.headline ?? f.summary}</span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
            {showRestaurant && <span className="font-medium">{restaurant ? restaurant.name.replace("Ресторан ", "") : "Вся сеть"}</span>}
            <span className="inline-flex items-center gap-1">
              <Icon size={13} strokeWidth={1.75} aria-hidden /> {processTitle(f.process)}
            </span>
            {work.line && <span className={cx("font-medium", LINE_TONE[work.line.tone])}>{work.line.text}</span>}
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="hidden sm:inline">
            <StagePill f={f} />
          </span>
          <ChevronRight size={18} className="text-ink-3 transition group-hover:translate-x-0.5 group-hover:text-ink" />
        </span>
      </Link>
    </motion.li>
  );
}

function Group({ title, items, max, showRestaurant }: { title: string; items: Finding[]; max: number; showRestaurant: boolean }) {
  if (!items.length) return null;
  const sum = items.reduce((acc, f) => acc + (f.effectRubMonth ?? 0), 0);
  return (
    <section className="rounded-[18px] border border-line bg-surface p-2">
      <div className="flex items-baseline justify-between px-4 pt-3 pb-2">
        <h2 className="font-display text-base font-semibold">{title}</h2>
        <span className="text-sm text-ink-3">
          {plural(items.length, ["находка", "находки", "находок"])}
          {sum > 0 && <> · {rub(sum)} в месяц</>}
        </span>
      </div>
      <ul className="divide-y divide-line">
        <AnimatePresence initial={false}>
          {items.map((f, i) => (
            <Row key={f.id} f={f} max={max} showRestaurant={showRestaurant} index={i} />
          ))}
        </AnimatePresence>
      </ul>
    </section>
  );
}

export function FindingsPage() {
  const viewer = useViewer();
  const workOf = useWork();
  const [kind, setKind] = useState<FindingKind | "all">("all");
  const [process, setProcess] = useState<ProcessKey | "all">("all");
  const [restaurant, setRestaurant] = useState<string>("all");
  const [stage, setStage] = useState<Stage>("all");
  const [lateOnly, setLateOnly] = useState(false);
  if (!viewer) return null;

  const scope = FINDINGS.filter((f) => viewer.isHq || f.restaurantId === viewer.restaurantCode);
  const stageCount = (s: Stage) => scope.filter((f) => s === "all" || workOf(f).stage === s).length;
  const lateCount = scope.filter((f) => workOf(f).late > 0).length;
  const filtered = scope.filter(
    (f) =>
      (process === "all" || f.process === process) &&
      (restaurant === "all" || (f.restaurantId ?? "net") === restaurant) &&
      (stage === "all" || workOf(f).stage === stage) &&
      (!lateOnly || workOf(f).late > 0),
  );
  const byMoney = (a: Finding, b: Finding) => (b.effectRubMonth ?? -1) - (a.effectRubMonth ?? -1);
  const ofKind = (k: FindingKind) => filtered.filter((f) => f.kind === k && f.effectRubMonth !== null).sort(byMoney);
  const unestimated = filtered.filter((f) => f.effectRubMonth === null && (kind === "all" || f.kind === kind));
  const max = Math.max(...filtered.map((f) => f.effectRubMonth ?? 0), 1);
  const total = (k: FindingKind) => filtered.filter((f) => f.kind === k).reduce((acc, f) => acc + (f.effectRubMonth ?? 0), 0);
  const count = (k: FindingKind) => filtered.filter((f) => f.kind === k).length;
  const filtersOn = process !== "all" || restaurant !== "all" || stage !== "all" || lateOnly;
  const shownKinds = (kind === "all" ? ["problem", "opportunity"] : [kind]) as FindingKind[];
  const empty = shownKinds.every((k) => !ofKind(k).length) && !unestimated.length;

  return (
    <div className="mx-auto max-w-[1040px]">
      <PageTitle
        title={viewer.isHq ? "Находки сети" : "Все находки ресторана"}
        subtitle={
          viewer.isHq
            ? "Все, что су-шеф нашел, и работа по каждой находке: задачи директорам, проверки и результат. Самые дорогие — сверху."
            : "Что су-шеф нашел в данных: где теряем деньги и где можно заработать. Самые дорогие — сверху."
        }
      />

      <CheckedFindingsSection />

      {/* Kind switch: two summary cards that also filter */}
      <Reveal>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["problem", "opportunity"] as const).map((k) => {
            const active = kind === k;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setKind(active ? "all" : k)}
                aria-pressed={active}
                className={cx(
                  "rounded-[18px] border bg-surface p-5 text-left transition",
                  active ? cx("ring-2", KIND[k].ring, "border-transparent") : "border-line hover:border-ink-3",
                  kind !== "all" && !active && "opacity-55",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-ink">{KIND[k].title}</span>
                  <span className={cx("num rounded-full px-2 py-0.5 text-xs font-semibold", KIND[k].soft)}>{count(k)}</span>
                </div>
                <div className={cx("num mt-2 font-display text-[28px] leading-none font-semibold", KIND[k].text)}>{rub(total(k))}</div>
                <div className="mt-1 text-xs text-ink-3">в месяц · {KIND[k].hint}</div>
              </button>
            );
          })}
        </div>
      </Reveal>

      {/* Secondary filters in one compact row */}
      <Reveal index={1}>
        <div className="mt-4 mb-5 flex flex-wrap items-center gap-2">
          {viewer.isHq && (
            <select value={restaurant} onChange={(e) => setRestaurant(e.target.value)} aria-label="Ресторан" className={select}>
              <option value="all">Все рестораны</option>
              {RESTAURANTS.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
              <option value="net">Общие для сети</option>
            </select>
          )}
          <select value={process} onChange={(e) => setProcess(e.target.value as ProcessKey | "all")} aria-label="Процесс" className={select}>
            <option value="all">Все процессы</option>
            {PROCESSES.filter((p) => scope.some((f) => f.process === p.key)).map((p) => (
              <option key={p.key} value={p.key}>
                {p.title}
              </option>
            ))}
          </select>
          <div className="flex max-w-full overflow-x-auto rounded-[10px] border border-line-strong bg-surface p-0.5" role="group" aria-label="Этап">
            {STAGES.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => setStage(s.key)}
                aria-pressed={stage === s.key}
                className={cx(
                  "relative h-9 shrink-0 whitespace-nowrap rounded-[8px] px-3 text-sm transition-colors",
                  stage === s.key ? "text-white" : "text-ink-2 hover:text-ink",
                )}
              >
                {stage === s.key && (
                  <motion.span layoutId="stage-pill" className="absolute inset-0 rounded-[8px] bg-ink" transition={{ type: "spring", stiffness: 500, damping: 36 }} />
                )}
                <span className="relative">
                  {s.label} <span className="num opacity-60">{stageCount(s.key)}</span>
                </span>
              </button>
            ))}
          </div>
          {lateCount > 0 && (
            <button
              type="button"
              onClick={() => setLateOnly((v) => !v)}
              aria-pressed={lateOnly}
              className={cx(
                "h-10 rounded-[10px] border px-3 text-sm transition",
                lateOnly ? "border-loss-icon bg-loss-soft font-medium text-loss" : "border-line-strong bg-surface text-loss hover:border-loss-icon",
              )}
            >
              Есть просрочки · {lateCount}
            </button>
          )}
          {filtersOn && (
            <button
              type="button"
              onClick={() => {
                setProcess("all");
                setRestaurant("all");
                setStage("all");
                setLateOnly(false);
              }}
              className="inline-flex h-10 items-center gap-1.5 px-2 text-sm text-ink-3 hover:text-ink"
            >
              <RotateCcw size={14} /> Сбросить
            </button>
          )}
        </div>
      </Reveal>

      <Reveal index={2}>
        {empty ? (
          <EmptyState title="Под эти условия находок нет">Измените фильтры или нажмите «Сбросить».</EmptyState>
        ) : (
          <div className="space-y-4">
            {shownKinds.map((k) => (
              <Group key={k} title={KIND[k].title} items={ofKind(k)} max={max} showRestaurant={viewer.isHq} />
            ))}
            <Group title="Без оценки в рублях — но важно для точности" items={unestimated} max={max} showRestaurant={viewer.isHq} />
          </div>
        )}
      </Reveal>
    </div>
  );
}
