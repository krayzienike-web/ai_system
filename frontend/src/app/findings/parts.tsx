import { Link } from "@tanstack/react-router";
import { ArrowRight, MessageCircle } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { useAppContext, useCreateTasks } from "../../api/hooks";
import type { ApiFinding } from "../../api/types";
import { ConfidenceNote } from "../../ds/ai";
import { Button, cx, Dialog, EASE, Pill, type Tone } from "../../ds/primitives";
import { CYCLE, PROCESS_ICON } from "../../ds/viz";
import { ddmm, money, perMonth } from "../../lib/format";
import { useUi } from "../../state/ui";

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

/** "This week's action": the decision-ready version of a finding. */
export function ActionCard({ f, index, onTake }: { f: ApiFinding; index: number; onTake: () => void }) {
  const { openChat } = useUi();
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -120, y: -60, scale: 0.85, transition: { duration: 0.45, ease: EASE } }}
      transition={{ duration: 0.4, ease: EASE, delay: 0.1 + index * 0.08 }}
      className="flex flex-col rounded-[18px] border border-line bg-surface p-5 shadow-[var(--shadow-raised)]"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-sm font-semibold text-ink-3">Дело {index + 1}</span>
        <ProcessChip f={f} />
      </div>
      <h3 className="mt-3 text-[17px] leading-snug font-semibold text-ink">{f.title}</h3>
      <div className="mt-1.5">
        <MoneyWords f={f} />
      </div>
      <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-2">{text(f)}</p>
      <div className="mt-4 rounded-[12px] bg-paper px-3 py-2.5 text-sm">
        <span className="text-ink-3">Первый шаг: </span>
        <span className="text-ink">{f.actions[0]}</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={onTake}>
          Взять в работу
        </Button>
        <Link to="/findings/$findingId" params={{ findingId: f.id }} className="inline-flex h-10 items-center gap-1 px-2 text-sm font-medium text-ink-2 hover:text-ink">
          Подробнее <ArrowRight size={14} />
        </Link>
        <button
          type="button"
          onClick={() => openChat({ title: f.title, findingId: f.id })}
          className="ml-auto grid h-10 w-10 place-items-center rounded-full text-ink-3 hover:bg-paper hover:text-ink"
          aria-label="Спросить су-шефа"
          title="Спросить су-шефа"
        >
          <MessageCircle size={18} />
        </button>
      </div>
    </motion.article>
  );
}

/** A finding in a list: one line to scan, click for details. */
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

/** The director takes a finding: the chosen steps become one task (with a checklist), due by the chosen date. */
export function TakeToWorkDialog({ f, open, onClose }: { f: ApiFinding; open: boolean; onClose: () => void }) {
  const create = useCreateTasks();
  const context = useAppContext();
  const { notify } = useUi();
  const [steps, setSteps] = useState<boolean[]>(() => f.actions.map((_, i) => i === 0));
  const [due, setDue] = useState(1);
  const options = context.data?.due_options ?? [];
  const chosen = f.actions.filter((_, i) => steps[i]);
  const effect = money(f.effect_rub_month);
  const option = options[due];

  return (
    <Dialog open={open} onClose={onClose} title="Взять в работу">
      <div className="space-y-5 text-sm">
        <fieldset>
          <legend className="mb-2 font-medium text-ink">Что сделать</legend>
          <div className="space-y-2">
            {f.actions.map((a, i) => (
              <label key={a} className="flex cursor-pointer items-start gap-2.5 rounded-[10px] border border-line p-3 hover:border-brand">
                <input
                  type="checkbox"
                  checked={steps[i] ?? false}
                  onChange={() => setSteps((s) => s.map((v, j) => (j === i ? !v : v)))}
                  className="mt-0.5 h-4 w-4 accent-[#0a8f84]"
                />
                <span>{a}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 font-medium text-ink">Срок</legend>
          <div className="flex flex-wrap gap-2">
            {options.map((d, i) => (
              <button
                key={d.days}
                type="button"
                onClick={() => setDue(i)}
                aria-pressed={due === i}
                className={cx(
                  "rounded-full border px-3 py-1.5",
                  due === i ? "border-brand bg-brand-soft font-medium text-brand-strong" : "border-line-strong text-ink-2",
                )}
              >
                {d.label} <span className="text-ink-3">· до {ddmm(d.due_on)}</span>
              </button>
            ))}
          </div>
        </fieldset>
        <div className="rounded-[12px] bg-paper p-3.5 text-ink-2">
          <div className="mb-1 font-medium text-ink">Так будет выглядеть задача</div>
          {chosen.length ? chosen.join("; ") : "Выберите хотя бы один шаг"}
          {option && <>. Срок — {ddmm(option.due_on)}.</>}
          {effect !== null && context.data?.next_count_on && (
            <> Если сработает, эффект — до {perMonth(effect)} — проверим после инвентаризации {ddmm(context.data.next_count_on)}.</>
          )}
        </div>
        {create.isError && <p className="text-loss">Не получилось поставить задачу. Попробуйте еще раз.</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            disabled={!chosen.length || !option || create.isPending}
            onClick={() =>
              create.mutate(
                {
                  title: chosen[0]!,
                  checklist: chosen.length > 1 ? chosen : [],
                  finding_id: f.id,
                  due_on: option!.due_on,
                },
                {
                  onSuccess: () => {
                    notify("Задача в «Моих задачах»");
                    onClose();
                  },
                },
              )
            }
          >
            Взять в работу
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function FindingConfidence({ f }: { f: ApiFinding }) {
  if (!f.confidence) return null;
  return <ConfidenceNote confidence={f.confidence} reason={f.view?.confidence_note ?? "по загруженным данным"} />;
}
