import { Link, useSearch } from "@tanstack/react-router";
import { ChevronRight, RotateCcw } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { useFindingBoard, useRestaurants } from "../../api/hooks";
import type { ApiFinding, FindingBoard } from "../../api/types";
import { cx, EASE, EmptyState, LoadError, PageTitle, Reveal, Skeleton } from "../../ds/primitives";
import { PROCESS_ICON } from "../../ds/viz";
import { money, plural, rub } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { PROCESS_TITLE, StagePill, workLine } from "./parts";

type Stage = "all" | "new" | "doing" | "checking" | "done";

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
function Row({ f, max, showRestaurant, index }: { f: ApiFinding; max: number; showRestaurant: boolean; index: number }) {
  const line = workLine(f);
  const Icon = PROCESS_ICON[f.process];
  const k = KIND[f.kind];
  const effect = money(f.effect_rub_month);
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
          {effect !== null ? (
            <>
              <span className={cx("num block font-display text-[19px] leading-none font-semibold", k.text)}>{rub(effect)}</span>
              <span className="mt-1 block text-[11px] text-ink-3">в месяц</span>
              <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-ink/5">
                <motion.span
                  className={cx("block h-full rounded-full", k.bar)}
                  initial={{ width: 0 }}
                  animate={{ width: `${max ? (effect / max) * 100 : 0}%` }}
                  transition={{ duration: 0.5, ease: EASE, delay: 0.1 + Math.min(index, 10) * 0.025 }}
                />
              </span>
            </>
          ) : (
            <span className="block text-xs leading-tight text-ink-3">{f.effect_note ?? "без оценки"}</span>
          )}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium text-ink group-hover:underline">{f.title}</span>
          <span className="mt-0.5 block truncate text-sm text-ink-3">{f.headline ?? f.view?.summary}</span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
            {showRestaurant && <span className="font-medium">{f.restaurant_name ? f.restaurant_name.replace("Ресторан ", "") : "Вся сеть"}</span>}
            <span className="inline-flex items-center gap-1">
              <Icon size={13} strokeWidth={1.75} aria-hidden /> {PROCESS_TITLE[f.process]}
            </span>
            {line && <span className={cx("font-medium", LINE_TONE[line.tone])}>{line.text}</span>}
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

function Group({ g, max, showRestaurant }: { g: FindingBoard["groups"][number]; max: number; showRestaurant: boolean }) {
  const total = money(g.total) ?? 0;
  return (
    <section className="rounded-[18px] border border-line bg-surface p-2">
      <div className="flex items-baseline justify-between px-4 pt-3 pb-2">
        <h2 className="font-display text-base font-semibold">{g.title}</h2>
        <span className="text-sm text-ink-3">
          {plural(g.count, ["находка", "находки", "находок"])}
          {total > 0 && <> · {rub(total)} в месяц</>}
        </span>
      </div>
      <ul className="divide-y divide-line">
        <AnimatePresence initial={false}>
          {g.items.map((f, i) => (
            <Row key={f.id} f={f} max={max} showRestaurant={showRestaurant} index={i} />
          ))}
        </AnimatePresence>
      </ul>
    </section>
  );
}

export function FindingsPage() {
  const viewer = useViewer();
  const restaurants = useRestaurants();
  const [kind, setKind] = useState<"problem" | "opportunity" | "all">("all");
  const search: { restaurant?: string; process?: string } = useSearch({ strict: false });
  const [process, setProcess] = useState<string>(search.process ?? "all");
  const [restaurant, setRestaurant] = useState<string>(search.restaurant ?? "all");
  const [stage, setStage] = useState<Stage>("all");
  const [lateOnly, setLateOnly] = useState(false);
  const board = useFindingBoard({
    kind: kind === "all" ? undefined : kind,
    process: process === "all" ? undefined : process,
    restaurant: restaurant === "all" ? undefined : restaurant,
    stage: stage === "all" ? undefined : stage,
    late: lateOnly,
  });
  if (!viewer) return null;
  const b = board.data;
  const filtersOn = process !== "all" || restaurant !== "all" || stage !== "all" || lateOnly;

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

      {board.isError ? (
        <LoadError error={board.error} />
      ) : !b ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          {/* Kind switch: two summary cards that also filter */}
          <Reveal>
            <div className="grid gap-3 sm:grid-cols-2">
              {b.kinds.map((t) => {
                const k = t.kind as keyof typeof KIND;
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
                      <span className={cx("num rounded-full px-2 py-0.5 text-xs font-semibold", KIND[k].soft)}>{t.count}</span>
                    </div>
                    <div className={cx("num mt-2 font-display text-[28px] leading-none font-semibold", KIND[k].text)}>{rub(money(t.total) ?? 0)}</div>
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
                  {(restaurants.data ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                  <option value="net">Общие для сети</option>
                </select>
              )}
              <select value={process} onChange={(e) => setProcess(e.target.value)} aria-label="Процесс" className={select}>
                <option value="all">Все процессы</option>
                {b.processes.map((p) => (
                  <option key={p} value={p}>
                    {PROCESS_TITLE[p as ApiFinding["process"]]}
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
                      {s.label} <span className="num opacity-60">{b.stage_counts[s.key] ?? 0}</span>
                    </span>
                  </button>
                ))}
              </div>
              {b.late_count > 0 && (
                <button
                  type="button"
                  onClick={() => setLateOnly((v) => !v)}
                  aria-pressed={lateOnly}
                  className={cx(
                    "h-10 rounded-[10px] border px-3 text-sm transition",
                    lateOnly ? "border-loss-icon bg-loss-soft font-medium text-loss" : "border-line-strong bg-surface text-loss hover:border-loss-icon",
                  )}
                >
                  Есть просрочки · {b.late_count}
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
            {b.groups.length === 0 ? (
              <EmptyState title="Под эти условия находок нет">Измените фильтры или нажмите «Сбросить».</EmptyState>
            ) : (
              <div className="space-y-4">
                {b.groups.map((g) => (
                  <Group key={g.key} g={g} max={money(b.max_effect) ?? 0} showRestaurant={viewer.isHq} />
                ))}
              </div>
            )}
          </Reveal>
        </>
      )}
    </div>
  );
}
