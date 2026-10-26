import { Link } from "@tanstack/react-router";
import { Check, Clock, ShieldCheck, XCircle } from "lucide-react";

import { useCheckedFindings, useRestaurants, useReviewFindings } from "../../api/hooks";
import type { ApiFinding } from "../../api/types";
import { cx, Reveal } from "../../ds/primitives";
import { perMonth } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";

const MODULE_TITLE: Record<string, string> = {
  M1: "потери по техкартам",
  M2: "фудкост",
  M3: "закупочные цены",
  M4: "инвентаризации",
  M5: "списания",
  M6: "риск дефицита",
  M7: "качество данных",
};

const day = (iso: string | null | undefined) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }).replace(".", "") : "";

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
  const confirmed = f.review_status === "confirmed";
  const rejected = f.review_status === "rejected";
  const steps: { title: string; note: string; state: StepState }[] = [
    { title: "Найдено движком", note: `${day(f.found_on)}${f.module ? ` · ${f.module} ${MODULE_TITLE[f.module] ?? ""}` : ""}`, state: "done" },
    {
      title: rejected ? "Отклонено при проверке" : confirmed ? "Проверено" : "На проверке",
      note: confirmed || rejected ? `${day(f.reviewed_on)}${f.reviewed_by_name ? ` · ${f.reviewed_by_name}` : ""}` : "ждет решения управляющей компании",
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

/** Engine findings that passed the check: the bridge from «Проверка находок» to the working list. */
export function CheckedFindingsSection() {
  const viewer = useViewer();
  const checked = useCheckedFindings();
  const pending = useReviewFindings("pending", Boolean(viewer?.isHq));
  const restaurants = useRestaurants();
  if (!viewer) return null;
  const items = (checked.data ?? []).filter((f) => f.module && f.review_status === "confirmed");
  const waiting = pending.data?.length ?? 0;
  if (!items.length && !(viewer.isHq && waiting)) return null;
  const name = (id: string | null) => (id ? (restaurants.data?.find((r) => r.id === id)?.name ?? id) : "Вся сеть");

  return (
    <Reveal>
      <section className="mt-6 rounded-[18px] border border-line bg-surface p-5" aria-labelledby="checked-title">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="checked-title" className="flex items-center gap-2 font-display text-lg font-semibold">
            <ShieldCheck size={18} className="text-brand" /> Найдено движком и проверено
          </h2>
          {viewer.isHq && waiting > 0 && (
            <Link to="/review" className="text-sm font-medium text-brand-strong hover:underline">
              Ждут проверки: {waiting} →
            </Link>
          )}
        </div>
        <p className="mt-1 text-sm text-ink-3">
          Находки, которые посчитал движок по загруженным данным и подтвердила управляющая компания.
        </p>
        {items.length === 0 ? (
          <p className="mt-4 text-sm text-ink-2">Пока ни одна находка движка не подтверждена.</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {items.map((f) => (
              <li key={f.id} className="rounded-[14px] border border-line p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-xs font-semibold text-ink-2">
                    {name(f.restaurant_id)} · {f.kind === "problem" ? "проблема" : "возможность"}
                  </span>
                  <span className={cx("num font-semibold", f.kind === "problem" ? "text-loss" : "text-gain")}>
                    {f.effect_rub_month ? perMonth(Number(f.effect_rub_month)) : <span className="text-sm font-normal text-ink-3">{f.effect_note}</span>}
                  </span>
                </div>
                <p className="mt-1 font-semibold">{f.title}</p>
                {f.headline && <p className="mt-1 text-sm text-ink-2">{f.headline}</p>}
                <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
                  <ReviewTrace f={f} compact />
                  {viewer.isHq && (
                    <Link to="/review/$findingId" params={{ findingId: f.id }} className="text-sm font-medium text-brand-strong hover:underline">
                      Расчет и проверка →
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Reveal>
  );
}
