import { Link } from "@tanstack/react-router";
import { ArrowRight, MessageCircle } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { ConfidenceNote } from "../../ds/ai";
import { Button, cx, Dialog, EASE, Pill, type Tone } from "../../ds/primitives";
import { CYCLE, PROCESS_ICON } from "../../ds/viz";
import { perMonth } from "../../lib/format";
import { PERIOD } from "../../mock/data";
import { cycleStage, processTitle, restaurantByCode } from "../../mock/selectors";
import type { Finding, FindingStatus } from "../../mock/types";
import { usePrototype } from "../../state/prototype";

export function useStatus(f: Finding): FindingStatus {
  const { findingStatus } = usePrototype();
  return findingStatus[f.id] ?? f.status;
}

/** Money in words, colored by meaning: "Теряем 38 тыс ₽ в месяц" / "Можно заработать …". */
export function MoneyWords({ f, size = "md" }: { f: Finding; size?: "md" | "lg" }) {
  const big = size === "lg";
  if (f.effectRubMonth === null) {
    return <span className={cx("font-medium text-ink-2", big ? "text-lg" : "text-sm")}>{f.effectNote ?? "Сумму пока не оценить"}</span>;
  }
  const loss = f.kind === "problem";
  return (
    <span className={cx("leading-tight", big ? "text-lg" : "text-sm")}>
      <span className="text-ink-2">{loss ? "Теряем " : "Можно заработать "}</span>
      <span className={cx("num font-semibold", loss ? "text-loss" : "text-gain")}>{perMonth(f.effectRubMonth)}</span>
    </span>
  );
}

const STAGE_TONE: Tone[] = ["neutral", "info", "brand", "gain"];

export function StagePill({ f }: { f: Finding }) {
  const status = useStatus(f);
  if (status === "disputed") return <Pill tone="warn">Оспорено</Pill>;
  const stage = cycleStage(status);
  return (
    <Pill tone={STAGE_TONE[stage]} icon={stage === 3}>
      {CYCLE[stage]}
    </Pill>
  );
}

export function ProcessChip({ f }: { f: Finding }) {
  const Icon = PROCESS_ICON[f.process];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-3">
      <Icon size={14} strokeWidth={1.75} aria-hidden />
      {processTitle(f.process)}
    </span>
  );
}

/** "This week's action": the decision-ready version of a finding. */
export function ActionCard({ f, index, onTake }: { f: Finding; index: number; onTake: () => void }) {
  const { openChat } = usePrototype();
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
      <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-2">{f.headline ?? f.summary}</p>
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
export function FindingRow({ f, showRestaurant }: { f: Finding; showRestaurant?: boolean }) {
  const Icon = PROCESS_ICON[f.process];
  const restaurant = f.restaurantId ? restaurantByCode(f.restaurantId) : null;
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
          {showRestaurant && <span className="text-ink-2">{restaurant ? restaurant.name : "Вся сеть"} · </span>}
          {f.headline ?? f.summary}
        </span>
      </span>
      <span className="col-start-2 sm:col-start-3 sm:row-start-1 sm:text-right">
        <MoneyWords f={f} />
      </span>
    </Link>
  );
}

// ------------------------------------------------------------------ dialogs

const DUE = [
  { label: "За 3 дня", date: "26.10" },
  { label: "За неделю", date: "30.10" },
  { label: "За 2 недели", date: "06.11" },
];

export function TakeToWorkDialog({ f, open, onClose }: { f: Finding; open: boolean; onClose: () => void }) {
  const { takeToWork } = usePrototype();
  const [steps, setSteps] = useState<boolean[]>(() => f.actions.map((_, i) => i === 0));
  const [due, setDue] = useState(1);
  const chosen = f.actions.filter((_, i) => steps[i]);

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
            {DUE.map((d, i) => (
              <button
                key={d.label}
                type="button"
                onClick={() => setDue(i)}
                aria-pressed={due === i}
                className={cx(
                  "rounded-full border px-3 py-1.5",
                  due === i ? "border-brand bg-brand-soft font-medium text-brand-strong" : "border-line-strong text-ink-2",
                )}
              >
                {d.label} <span className="text-ink-3">· до {d.date}</span>
              </button>
            ))}
          </div>
        </fieldset>
        <div className="rounded-[12px] bg-paper p-3.5 text-ink-2">
          <div className="mb-1 font-medium text-ink">Так будет выглядеть задача</div>
          {chosen.length ? chosen.join("; ") : "Выберите хотя бы один шаг"}. Срок — {DUE[due]!.date}.
          {f.effectRubMonth !== null && (
            <> Если сработает, вернет до {perMonth(f.effectRubMonth)} — проверим после инвентаризации {PERIOD.nextInventory.slice(0, 5)}.</>
          )}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            disabled={!chosen.length}
            onClick={() => {
              takeToWork(f.id, {
                id: `x-${f.id}`,
                restaurantId: f.restaurantId ?? "",
                title: chosen[0]!,
                checklist: chosen.length > 1 ? chosen : undefined,
                source: "Взято из сводки недели",
                findingId: f.id,
                due: DUE[due]!.date,
                status: "assigned",
              });
              onClose();
            }}
          >
            Взять в работу
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

const REASONS = ["Цифры не сходятся с моими", "Причина другая", "Уже исправили", "Другое"];

export function DisputeDialog({ f, open, onClose }: { f: Finding; open: boolean; onClose: () => void }) {
  const { dispute } = usePrototype();
  const [reason, setReason] = useState(REASONS[0]!);
  const [comment, setComment] = useState("");
  return (
    <Dialog open={open} onClose={onClose} title="Не согласен с выводом">
      <div className="space-y-4 text-sm">
        <div className="space-y-2">
          {REASONS.map((r) => (
            <label key={r} className="flex cursor-pointer items-center gap-2.5">
              <input type="radio" name="reason" checked={reason === r} onChange={() => setReason(r)} className="h-4 w-4 accent-[#0a8f84]" />
              {r}
            </label>
          ))}
        </div>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          placeholder="Что на самом деле происходит? Это поможет системе и управляющей компании"
          aria-label="Комментарий"
          className="w-full rounded-[10px] border border-line-strong p-3 outline-none focus:border-brand"
        />
        <p className="text-ink-3">Ваш ответ увидит управляющая компания. Пока она не ответит, находка не попадет в ваши дела.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              dispute(f.id, reason, comment);
              onClose();
            }}
          >
            Отправить
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function FindingConfidence({ f }: { f: Finding }) {
  return <ConfidenceNote confidence={f.confidence} reason={f.confidenceNote} />;
}
