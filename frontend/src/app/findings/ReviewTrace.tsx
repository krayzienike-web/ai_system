import { Check, Clock, XCircle } from "lucide-react";

import type { ApiFinding } from "../../api/types";
import { cx } from "../../ds/primitives";
import { dayMonth as day, MODULE_TITLE } from "../../lib/format";

type StepState = "done" | "now" | "todo" | "bad";
const DOT: Record<StepState, string> = {
  done: "bg-brand text-white border-brand",
  now: "bg-surface text-warn border-warn",
  todo: "bg-surface text-ink-3 border-line-strong",
  bad: "bg-loss text-white border-loss",
};

/**
 * The path of an engine finding: found by the engine → checked by a person → in the working list.
 * Every step says when and who, so a finding can always be traced back to its check.
 */
export function ReviewTrace({ f, compact = false }: { f: ApiFinding; compact?: boolean }) {
  const confirmed = f.review_status === "confirmed" || f.review_status === null;
  const rejected = f.review_status === "rejected";
  const steps: { title: string; note: string; state: StepState }[] = [
    { title: "Найдено движком", note: `${day(f.found_on)}${f.module ? ` · ${f.module} ${(MODULE_TITLE[f.module] ?? "").toLowerCase()}` : ""}`, state: "done" },
    {
      title: rejected ? "Отклонено при проверке" : f.review_status === null ? "Без ручной проверки" : confirmed ? "Проверено" : "На проверке",
      note: f.review_status === null ? "проверка выключена в настройках" : confirmed || rejected ? `${day(f.reviewed_on)}${f.reviewed_by_name ? ` · ${f.reviewed_by_name}` : ""}` : "ждет решения управляющей компании",
      state: confirmed ? "done" : rejected ? "bad" : "now",
    },
    {
      title: "В находках",
      note: confirmed ? "видна в списке находок и директору ресторана" : rejected ? "не попадет в работу" : "появится после подтверждения",
      state: confirmed ? "done" : "todo",
    },
  ];
  return (
    <ol aria-label="Путь находки" className={cx("flex flex-wrap gap-x-5 gap-y-2", compact ? "text-xs" : "text-sm")}>
      {steps.map((s, i) => (
        <li key={s.title} className="flex min-w-0 items-start gap-2">
          <span className={cx("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border-2", DOT[s.state])}>
            {s.state === "done" ? <Check size={11} strokeWidth={3} /> : s.state === "bad" ? <XCircle size={11} /> : s.state === "now" ? <Clock size={10} /> : <span className="text-[10px]">{i + 1}</span>}
          </span>
          <span className="min-w-0">
            <span className={cx("block font-medium", s.state === "todo" && "text-ink-3")}>{s.title}</span>
            <span className="block text-ink-3">{s.note}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
