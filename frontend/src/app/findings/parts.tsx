import { Link } from "@tanstack/react-router";

import type { ApiFinding } from "../../api/types";
import { ConfidenceNote } from "../../ds/ai";
import { cx, Pill, type Tone } from "../../ds/primitives";
import { CYCLE, PROCESS_ICON } from "../../ds/viz";
import { money, perMonth } from "../../lib/format";

export const PROCESS_TITLE: Record<ApiFinding["process"], string> = {
  purchasing: "Закупка",
  receiving: "Приемка",
  storage: "Хранение",
  production: "Производство (ТТК)",
  writeoffs: "Списания",
  inventory: "Инвентаризация",
  accounting: "Учет и данные",
  planning: "Планирование запасов",
};

export const STAGE_INDEX = { new: 0, doing: 1, checking: 2, done: 3 } as const;

/** Money in words, colored by meaning: "Теряем 38 тыс ₽ в месяц" / "Можно заработать …". */
export function MoneyWords({ f, size = "md" }: { f: ApiFinding; size?: "md" | "lg" }) {
  const big = size === "lg";
  const effect = money(f.effect_rub_month);
  if (effect === null) {
    return <span className={cx("font-medium text-ink-2", big ? "text-lg" : "text-sm")}>{f.effect_note ?? "Сумму пока не оценить"}</span>;
  }
  const loss = f.kind === "problem";
  return (
    <span className={cx("leading-tight", big ? "text-lg" : "text-sm")}>
      <span className="text-ink-2">{loss ? "Теряем " : "Можно заработать "}</span>
      <span className={cx("num font-semibold", loss ? "text-loss" : "text-gain")}>{perMonth(effect)}</span>
    </span>
  );
}

const STAGE_TONE: Tone[] = ["neutral", "info", "brand", "gain"];

export function StagePill({ f }: { f: ApiFinding }) {
  const stage = STAGE_INDEX[f.work.stage];
  return (
    <Pill tone={STAGE_TONE[stage]} icon={stage === 3}>
      {CYCLE[stage]}
    </Pill>
  );
}

/** One line about the work on a finding, from the API's work state; null when nothing is going on. */
export function workLine(f: ApiFinding): { text: string; tone: "loss" | "gain" | "info" | "warn" } | null {
  const w = f.work;
  const confirmed = money(w.confirmed_rub_month) ?? 0;
  if (w.stage === "done") return { text: confirmed ? `Сработало: +${perMonth(confirmed)}` : "Есть результат", tone: "gain" };
  if (w.stage === "checking") return { text: "Идет проверка", tone: w.tasks_late ? "loss" : "info" };
  if (w.stage === "doing") {
    const text = w.tasks_total
      ? `Задачи: сделано ${w.tasks_done} из ${w.tasks_total}${w.tasks_late ? ` · просрочено ${w.tasks_late}` : ""}`
      : "В работе";
    return { text, tone: w.tasks_late ? "loss" : "info" };
  }
  return w.check_waiting_launch ? { text: "Проверка ждет запуска", tone: "warn" } : null;
}

export function ProcessChip({ f }: { f: ApiFinding }) {
  const Icon = PROCESS_ICON[f.process];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-3">
      <Icon size={14} strokeWidth={1.75} aria-hidden />
      {PROCESS_TITLE[f.process]}
    </span>
  );
}

const text = (f: ApiFinding) => f.headline ?? f.view?.summary ?? "";

/** One finding in a list: title, place, money, its stage; opens the card. */
export function FindingRow({ f, showRestaurant }: { f: ApiFinding; showRestaurant?: boolean }) {
  const Icon = PROCESS_ICON[f.process];
  const loss = f.kind === "problem";
  return (
    <Link
      to="/findings/$findingId"
      params={{ findingId: f.id }}
      className="group grid grid-cols-[40px_1fr] gap-x-3 gap-y-1 rounded-[14px] px-3 py-3.5 transition-colors hover:bg-paper sm:grid-cols-[40px_1fr_auto]"
    >
      <span className={cx("grid h-10 w-10 place-items-center rounded-[11px]", loss ? "bg-loss-soft text-loss" : "bg-gain-soft text-gain")}>
        <Icon size={18} strokeWidth={1.75} aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-ink group-hover:underline">{f.title}</span>
          <StagePill f={f} />
        </span>
        <span className="mt-0.5 line-clamp-2 block text-sm text-ink-3">
          {showRestaurant && <span className="text-ink-2">{f.restaurant_name ?? "Вся сеть"} · </span>}
          {text(f)}
        </span>
      </span>
      <span className="col-start-2 sm:col-start-3 sm:row-start-1 sm:text-right">
        <MoneyWords f={f} />
      </span>
    </Link>
  );
}

// ------------------------------------------------------------------ dialogs

export function FindingConfidence({ f }: { f: ApiFinding }) {
  if (!f.confidence) return null;
  return <ConfidenceNote confidence={f.confidence} reason={f.view?.confidence_note ?? "по загруженным данным"} />;
}
