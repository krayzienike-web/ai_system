import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft, CheckCircle2, CircleHelp, Sparkles, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { useCheck, useCheckAction, useCheckDraft, useProposeCheck } from "../../api/hooks";
import type { Check } from "../../api/types";
import { AiBadge, VerifiedNote } from "../../ds/ai";
import { Button, Card, cx, EASE, EmptyState, ErrorText, PageTitle, Pill, QuestionBlock, Reveal, Skeleton } from "../../ds/primitives";
import { ddmm, money, perMonth, plural, rub } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";
import { TaskTrace } from "../tasks/trace";

function RestaurantChips({ places, tone }: { places: { id: string; name: string }[]; tone: "test" | "control" }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {places.length ? (
        places.map((p) => (
          <span key={p.id} className={cx("rounded-full px-2.5 py-1 text-xs font-medium", tone === "test" ? "bg-brand text-white" : "bg-ink/10 text-ink")}>
            {p.name}
          </span>
        ))
      ) : (
        <span className="text-xs text-ink-3">сравниваем внутри ресторана</span>
      )}
    </div>
  );
}

const VERDICT = {
  confirmed: { title: "Сработало", Icon: CheckCircle2, cls: "bg-gain-soft text-gain" },
  inconclusive: { title: "Пока непонятно", Icon: CircleHelp, cls: "bg-warn-soft text-warn" },
  rejected: { title: "Не сработало", Icon: XCircle, cls: "bg-loss-soft text-loss" },
} as const;

const STATUS: Record<Check["status"], [string, "gain" | "info" | "neutral" | "warn"]> = {
  proposed: ["Ждет решения", "warn"],
  running: ["Идет", "info"],
  completed: ["Есть результат", "gain"],
  rejected: ["Отклонена", "neutral"],
};

export function CheckPage() {
  const { checkId } = useParams({ from: "/app/checks/$checkId" });
  const check = useCheck(checkId);
  const action = useCheckAction();
  const viewer = useViewer();
  const canLaunch = !!viewer?.can("experiments.launch");
  const { notify } = useUi();
  if (check.isError) return <EmptyState title="Проверка не найдена" />;
  const e = check.data;
  if (!e) return <Skeleton className="mx-auto h-96 max-w-[960px]" />;
  const effect = money(e.effect_rub_month) ?? 0;
  const expected = money(e.expected_rub_month) ?? 0;
  const rollout = money(e.rollout_rub_month);
  const weeks = e.weeks;
  const run = (a: "launch" | "reject" | "rollout", text: string) => action.mutate({ id: e.id, action: a }, { onSuccess: () => notify(text) });

  return (
    <div className="mx-auto max-w-[960px] space-y-6">
      <Link
        to={e.finding_id ? "/findings/$findingId" : "/findings"}
        params={e.finding_id ? { findingId: e.finding_id } : undefined}
        className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink"
      >
        <ArrowLeft size={14} /> {e.finding_id ? "К находке" : "Находки"}
      </Link>
      <Reveal>
        <section className="rounded-[24px] border border-line bg-surface p-6 sm:p-8">
          <Pill tone={STATUS[e.status][1]}>{STATUS[e.status][0]}</Pill>
          <h1 className="mt-3 font-display text-[28px] leading-tight font-semibold">{e.title}</h1>
          <p className="mt-2 max-w-[70ch] text-[17px] text-ink-2">{e.hypothesis}</p>
          {e.finding_id && e.finding_title && (
            <Link to="/findings/$findingId" params={{ findingId: e.finding_id }} className="mt-3 inline-block text-sm text-brand-strong hover:underline">
              Основание: {e.finding_title} →
            </Link>
          )}
        </section>
      </Reveal>

      {e.verdict && (
        <Reveal index={1}>
          <section className={cx("rounded-[24px] p-6 sm:p-8", VERDICT[e.verdict].cls)}>
            <div className="flex items-center gap-3">
              {(() => {
                const Icon = VERDICT[e.verdict].Icon;
                return <Icon size={32} />;
              })()}
              <span className="font-display text-3xl font-semibold">{VERDICT[e.verdict].title}</span>
            </div>
            {e.verdict === "confirmed" ? (
              <>
                <div className="mt-4 text-ink">
                  <span className="font-display text-4xl font-semibold">+{rub(effect)}</span>
                  <span className="ml-2 text-lg">в месяц</span>
                </div>
                <p className="mt-2 text-ink-2">
                  Скорее всего — от {rub(money(e.ci_low_rub_month) ?? 0)} до {rub(money(e.ci_high_rub_month) ?? 0)} в месяц. Ждали {rub(expected)}.
                </p>
                <EffectRange low={money(e.ci_low_rub_month) ?? 0} high={money(e.ci_high_rub_month) ?? 0} value={effect} expected={expected} />
              </>
            ) : (
              <p className="mt-4 text-ink">Эффекта не видно: ждали +{perMonth(expected)}, разница с ресторанами без изменений — в пределах случайных колебаний.</p>
            )}
            {e.result_text && <p className="mt-4 text-sm text-ink-2">{e.result_text.replace(" (разница разниц)", "")}</p>}
            {rollout !== null && (
              <div className="mt-5 flex flex-wrap items-center gap-3 rounded-[16px] bg-surface p-4">
                <span className="text-sm">
                  Если ввести во всех ресторанах: еще <span className="font-semibold text-gain">+{perMonth(rollout)}</span>
                </span>
                {e.rollout_on ? (
                  <span className="text-sm font-medium text-gain">Отправлено во все рестораны {ddmm(e.rollout_on)}</span>
                ) : canLaunch ? (
                  <Button variant="primary" disabled={action.isPending} onClick={() => run("rollout", "Задачи отправлены директорам всех ресторанов")}>
                    Ввести во всех ресторанах
                  </Button>
                ) : (
                  <span className="text-sm text-ink-3">Решение о вводе принимает администратор УК</span>
                )}
                <ErrorText error={action.error} className="w-full" />
              </div>
            )}
          </section>
        </Reveal>
      )}

      <Reveal index={2}>
        <QuestionBlock question="Как проверяем?" answer="Сравниваем, как изменился показатель там, где пробуем, и там, где ничего не меняли.">
          <div className="grid items-stretch gap-3 sm:grid-cols-[1fr_auto_1fr]">
            <div className="rounded-[16px] bg-brand-soft p-4">
              <div className="mb-2 text-sm font-medium text-brand-strong">Где пробуем</div>
              <RestaurantChips places={e.test ?? []} tone="test" />
            </div>
            <div className="grid place-items-center text-sm text-ink-3">сравниваем с</div>
            <div className="rounded-[16px] bg-paper p-4">
              <div className="mb-2 text-sm font-medium">С чем сравниваем</div>
              <RestaurantChips places={e.control ?? []} tone="control" />
            </div>
          </div>
          <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-3">Что считаем успехом</dt>
              <dd className="mt-0.5 font-medium">{e.metric}</dd>
            </div>
            <div>
              <dt className="text-ink-3">С каким периодом сравниваем</dt>
              <dd className="mt-0.5 font-medium">{e.baseline ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Сколько ждем</dt>
              <dd className="mt-0.5 font-medium">
                {plural(weeks, ["неделя", "недели", "недель"])} · {ddmm(e.starts_on)}–{ddmm(e.ends_on)}
              </dd>
            </div>
          </dl>
          {e.progress_text && e.status === "running" && <div className="mt-5 rounded-[12px] bg-info-soft p-3 text-sm text-info">{e.progress_text}</div>}
        </QuestionBlock>
      </Reveal>

      {e.tasks.length > 0 && (
        <Reveal index={3}>
          <QuestionBlock
            question="Что сделали в ресторанах?"
            answer={`Задач по проверке — ${e.tasks.length}, выполнено ${e.tasks.filter((t) => t.status === "done").length}. Отчеты директоров и результат — по каждой задаче.`}
            source={<VerifiedNote>результат считает система по данным, а не со слов исполнителя</VerifiedNote>}
          >
            <div className="grid gap-4 md:grid-cols-2">
              {e.tasks.map((t) => (
                <div key={t.id} className="rounded-[16px] border border-line p-4">
                  <div className="mb-3 font-medium">{t.restaurant_name}</div>
                  <TaskTrace task={t} />
                </div>
              ))}
            </div>
          </QuestionBlock>
        </Reveal>
      )}

      {e.status === "proposed" && (
        <Reveal index={3}>
          <QuestionBlock
            question="Что будет после запуска?"
            answer={`Директорам ${(e.test ?? []).map((p) => p.name).join(", ")} придут задачи со сроком и чек-листом. Замер начнется автоматически.`}
          >
            {canLaunch ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" size="lg" disabled={action.isPending} onClick={() => run("launch", "Проверка запущена, задачи отправлены директорам")}>
                  Запустить и поставить задачи
                </Button>
                <Button size="lg" disabled={action.isPending} onClick={() => run("reject", "Проверка отклонена")}>
                  Отклонить
                </Button>
              </div>
            ) : (
              <p className="text-sm text-ink-3">Проверка ждет решения администратора УК.</p>
            )}
            <ErrorText error={action.error} className="mt-2" />
          </QuestionBlock>
        </Reveal>
      )}
    </div>
  );
}

/** Effect range on a ruble scale with the expected value marked. */
function EffectRange({ low, high, value, expected }: { low: number; high: number; value: number; expected: number }) {
  const max = Math.max(high, expected) * 1.2;
  const x = (v: number) => `${(v / max) * 100}%`;
  return (
    <div className="relative mt-6 h-14" role="img" aria-label={`Эффект ${rub(value)}, скорее всего от ${rub(low)} до ${rub(high)}`}>
      <div className="absolute top-3 h-2 w-full rounded-full bg-surface/70" />
      <motion.div
        className="absolute top-3 h-2 rounded-full bg-gain-icon/40"
        initial={{ width: 0, left: x(low) }}
        animate={{ width: `calc(${x(high)} - ${x(low)})` }}
        transition={{ duration: 0.7, ease: EASE }}
        style={{ left: x(low) }}
      />
      <div className="absolute top-1 h-6 w-1.5 -translate-x-1/2 rounded bg-gain" style={{ left: x(value) }} />
      <div className="absolute top-0 h-8 border-l-2 border-dashed border-ink/50" style={{ left: x(expected) }} />
      <div className="absolute top-9 -translate-x-1/2 text-[11px] text-ink-2" style={{ left: x(expected) }}>
        ждали
      </div>
      <div className="absolute top-9 -translate-x-1/2 text-[11px] font-medium text-gain" style={{ left: x(value) }}>
        получили
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ wizard

/** The check the system drafted for a finding: HQ adjusts it and sends it to the admin to launch. */
export function NewCheckPage() {
  const { findingId } = useParams({ from: "/app/checks/new/$findingId" });
  const draft = useCheckDraft(findingId);
  const propose = useProposeCheck();
  const navigate = useNavigate();
  const { notify } = useUi();
  const [step, setStep] = useState(0);
  const [action, setAction] = useState(0);
  const [control, setControl] = useState<string[] | null>(null);
  const [weeks, setWeeks] = useState<number | null>(null);
  if (draft.isError) return <EmptyState title="Для этой находки проверку не поставить">{(draft.error as Error).message}</EmptyState>;
  const d = draft.data;
  if (!d) return <Skeleton className="mx-auto h-96 max-w-[760px]" />;
  const chosen = control ?? d.candidates.filter((c) => c.suggested).map((c) => c.restaurant_id);
  const duration = weeks ?? d.default_weeks;
  const steps = ["Что меняем", "Где пробуем", "Сколько ждем"];
  const controlNames = d.candidates.filter((c) => chosen.includes(c.restaurant_id)).map((c) => c.name);

  return (
    <div className="mx-auto max-w-[760px]">
      <Link to="/findings/$findingId" params={{ findingId: d.finding_id }} className="mb-4 inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> {d.finding_title}
      </Link>
      <PageTitle title="Новая проверка" subtitle="Су-шеф подготовил черновик — проверьте и поправьте" />
      <ol className="mb-6 grid grid-cols-3 gap-2">
        {steps.map((s, i) => (
          <li key={s}>
            <button type="button" onClick={() => setStep(i)} className="w-full text-left">
              <div className="h-1.5 overflow-hidden rounded-full bg-ink/10">
                <motion.div className="h-full bg-brand" animate={{ width: i <= step ? "100%" : "0%" }} transition={{ duration: 0.35 }} />
              </div>
              <div className={cx("mt-1.5 text-sm", i === step ? "font-semibold" : "text-ink-3")}>
                {i + 1}. {s}
              </div>
            </button>
          </li>
        ))}
      </ol>
      <Card className="overflow-hidden p-6">
        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }} transition={{ duration: 0.25, ease: EASE }}>
            {step === 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 font-medium">
                  Что меняем в ресторане <AiBadge basis="Варианты мер — из находки." />
                </div>
                {d.actions.map((a, i) => (
                  <label key={a} className={cx("flex cursor-pointer items-start gap-3 rounded-[12px] border p-4", action === i ? "border-brand bg-brand-soft" : "border-line")}>
                    <input type="radio" checked={action === i} onChange={() => setAction(i)} className="mt-1 h-4 w-4 accent-[#0a8f84]" />
                    {a}
                  </label>
                ))}
              </div>
            )}
            {step === 1 && (
              <div className="space-y-5">
                <div>
                  <div className="font-medium">Где пробуем</div>
                  <div className="mt-2">
                    <RestaurantChips places={[d.test]} tone="test" />
                  </div>
                  <p className="mt-2 text-sm text-ink-3">Там, где нашли проблему.</p>
                </div>
                <div>
                  <div className="flex items-center gap-2 font-medium">
                    С чем сравниваем <Sparkles size={14} className="text-brand" />
                  </div>
                  <p className="mt-1 text-sm text-ink-3">Су-шеф выбрал рестораны с похожей выручкой, где ничего не будем менять. Снимите галочку, если ресторан не подходит.</p>
                  <div className="mt-3 max-h-[320px] space-y-2 overflow-y-auto">
                    {d.candidates.map((c) => (
                      <label key={c.restaurant_id} className="flex items-center gap-3 rounded-[12px] border border-line p-3">
                        <input
                          type="checkbox"
                          checked={chosen.includes(c.restaurant_id)}
                          onChange={() =>
                            setControl(chosen.includes(c.restaurant_id) ? chosen.filter((x) => x !== c.restaurant_id) : [...chosen, c.restaurant_id])
                          }
                          className="h-4 w-4 accent-[#0a8f84]"
                        />
                        <span className="font-medium">{c.name}</span>
                        <span className="ml-auto text-xs text-ink-3">{c.reason}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            )}
            {step === 2 && (
              <div className="space-y-5">
                <div>
                  <div className="font-medium">Сколько ждем</div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-3">
                    {d.durations.map((o) => (
                      <button
                        key={o.weeks}
                        type="button"
                        onClick={() => setWeeks(o.weeks)}
                        className={cx("rounded-[12px] border p-3 text-left", duration === o.weeks ? "border-brand bg-brand-soft" : "border-line")}
                      >
                        <div className="font-semibold">{plural(o.weeks, ["неделя", "недели", "недель"])}</div>
                        <div className="text-xs text-ink-3">{o.note}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded-[14px] bg-paper p-4 text-sm">
                  <div className="font-medium">Что считаем успехом</div>
                  <div className="mt-1 text-ink-2">{d.success}</div>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </Card>

      <Card className="mt-4 p-5 text-sm">
        <div className="mb-1 font-medium">Итог</div>
        <div className="text-ink-2">
          {d.actions[action]} — в ресторане «{d.test.name}», сравниваем с {controlNames.length ? controlNames.join(", ") : "показателями внутри ресторана"},{" "}
          {plural(duration, ["неделя", "недели", "недель"])}. Директор получит задачу после запуска.
        </div>
        <div className="mt-1">
          <VerifiedNote>ожидаемый эффект +{perMonth(money(d.expected_rub_month) ?? 0)} — по данным находки</VerifiedNote>
        </div>
      </Card>
      {propose.isError && <p className="mt-2 text-sm text-loss">{(propose.error as Error).message}</p>}

      <div className="mt-4 flex justify-between gap-2">
        <Button variant="ghost" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          Назад
        </Button>
        {step < 2 ? (
          <Button variant="primary" onClick={() => setStep((s) => s + 1)}>
            Дальше
          </Button>
        ) : (
          <Button
            variant="primary"
            disabled={propose.isPending}
            onClick={() =>
              propose.mutate(
                { finding_id: d.finding_id, action: d.actions[action]!, control_ids: chosen, weeks: duration },
                {
                  onSuccess: () => {
                    notify("Проверка передана на запуск");
                    void navigate({ to: "/decisions" });
                  },
                },
              )
            }
          >
            Передать на запуск
          </Button>
        )}
      </div>
    </div>
  );
}
