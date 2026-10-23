import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft, CheckCircle2, CircleHelp, Sparkles, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { AiBadge, VerifiedNote } from "../../ds/ai";
import { Button, Card, cx, EASE, EmptyState, PageTitle, Pill, QuestionBlock, Reveal } from "../../ds/primitives";
import { perMonth, rub } from "../../lib/format";
import { EXPERIMENTS, RESTAURANTS } from "../../mock/data";
import { findingById, restaurantByCode } from "../../mock/selectors";
import type { Experiment } from "../../mock/types";
import { usePrototype } from "../../state/prototype";

const names = (codes: string[]) => codes.map((c) => restaurantByCode(c)?.name ?? c);

function RestaurantChips({ codes, tone }: { codes: string[]; tone: "test" | "control" }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {codes.length ? (
        names(codes).map((n) => (
          <span
            key={n}
            className={cx("rounded-full px-2.5 py-1 text-xs font-medium", tone === "test" ? "bg-brand text-white" : "bg-ink/10 text-ink")}
          >
            {n}
          </span>
        ))
      ) : (
        <span className="text-xs text-ink-3">сравниваем внутри ресторана</span>
      )}
    </div>
  );
}

function useStage(e: Experiment) {
  const { experimentStatus } = usePrototype();
  const d = experimentStatus[e.id];
  if (d === "rejected") return "rejected" as const;
  if (d === "approved") return "running" as const;
  return e.status;
}

function CheckCard({ e }: { e: Experiment }) {
  const stage = useStage(e);
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Link to="/checks/$checkId" params={{ checkId: e.id }} className="block rounded-[16px] border border-line bg-surface p-4 transition hover:border-ink-3">
        <div className="font-semibold">{e.title}</div>
        <div className="mt-3 space-y-2">
          <div className="text-[11px] text-ink-3">Где пробуем</div>
          <RestaurantChips codes={e.test} tone="test" />
        </div>
        <div className="mt-3 text-sm">
          {e.result ? (
            <span className="font-semibold text-gain">Сработало: +{perMonth(e.result.effectRubMonth)}</span>
          ) : stage === "rejected" ? (
            <span className="text-ink-3">Отклонено</span>
          ) : (
            <span className="text-ink-2">Ожидаем +{perMonth(e.expectedRubMonth)}</span>
          )}
        </div>
        {e.progress && stage === "running" && <div className="mt-2 text-xs text-ink-3">{e.progress.split(".")[0]}.</div>}
      </Link>
    </motion.div>
  );
}

export function ChecksPage() {
  const all = EXPERIMENTS;
  const { experimentStatus } = usePrototype();
  const stageOf = (e: Experiment) => (experimentStatus[e.id] === "approved" ? "running" : experimentStatus[e.id] === "rejected" ? "rejected" : e.status);
  const columns: { title: string; hint: string; items: Experiment[] }[] = [
    { title: "Ждут решения", hint: "Утвердите — и директора получат задачи", items: all.filter((e) => stageOf(e) === "proposed") },
    { title: "Идут", hint: "Собираем данные, вывод — в срок", items: all.filter((e) => stageOf(e) === "running") },
    { title: "Есть результат", hint: "Решите, предлагать ли всем ресторанам", items: all.filter((e) => stageOf(e) === "completed") },
  ];
  return (
    <div>
      <PageTitle
        title="Проверки"
        subtitle="Прежде чем менять всю сеть, пробуем на части ресторанов и сравниваем с остальными. Создать проверку можно из любой находки."
      />
      <div className="grid gap-4 lg:grid-cols-3">
        {columns.map((c, i) => (
          <Reveal key={c.title} index={i}>
            <div className="rounded-[20px] bg-ink/[0.035] p-3">
              <div className="mb-3 px-1">
                <div className="flex items-center gap-2 font-display font-semibold">
                  {c.title} <span className="num text-sm text-ink-3">{c.items.length}</span>
                </div>
                <div className="text-xs text-ink-3">{c.hint}</div>
              </div>
              <div className="space-y-3">
                {c.items.length ? c.items.map((e) => <CheckCard key={e.id} e={e} />) : <div className="px-1 py-6 text-center text-sm text-ink-3">Пусто</div>}
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </div>
  );
}

const VERDICT = {
  confirmed: { title: "Сработало", Icon: CheckCircle2, cls: "bg-gain-soft text-gain" },
  inconclusive: { title: "Пока непонятно", Icon: CircleHelp, cls: "bg-warn-soft text-warn" },
  rejected: { title: "Не сработало", Icon: XCircle, cls: "bg-loss-soft text-loss" },
} as const;

export function CheckPage() {
  const { checkId } = useParams({ from: "/app/checks/$checkId" });
  const e = EXPERIMENTS.find((x) => x.id === checkId);
  const { decideExperiment, proposeRollout, rollouts } = usePrototype();
  const stage = useStage(e ?? EXPERIMENTS[0]!);
  if (!e) return <EmptyState title="Проверка не найдена" />;
  const finding = e.findingId ? findingById(e.findingId) : undefined;

  return (
    <div className="mx-auto max-w-[960px] space-y-6">
      <Link to="/checks" className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> Проверки
      </Link>
      <Reveal>
        <section className="rounded-[24px] border border-line bg-surface p-6 sm:p-8">
          <Pill tone={stage === "completed" ? "gain" : stage === "running" ? "info" : stage === "rejected" ? "neutral" : "warn"}>
            {{ proposed: "Ждет решения", running: "Идет", completed: "Есть результат", rejected: "Отклонена" }[stage]}
          </Pill>
          <h1 className="mt-3 font-display text-[28px] leading-tight font-semibold">{e.title}</h1>
          <p className="mt-2 max-w-[70ch] text-[17px] text-ink-2">{e.hypothesis}</p>
          {finding && (
            <Link to="/findings/$findingId" params={{ findingId: finding.id }} className="mt-3 inline-block text-sm text-brand-strong hover:underline">
              Основание: {finding.title} →
            </Link>
          )}
        </section>
      </Reveal>

      {e.result && (
        <Reveal index={1}>
          <section className={cx("rounded-[24px] p-6 sm:p-8", VERDICT[e.result.verdict].cls)}>
            <div className="flex items-center gap-3">
              {(() => {
                const Icon = VERDICT[e.result.verdict].Icon;
                return <Icon size={32} />;
              })()}
              <span className="font-display text-3xl font-semibold">{VERDICT[e.result.verdict].title}</span>
            </div>
            <div className="mt-4 text-ink">
              <span className="font-display text-4xl font-semibold">+{rub(e.result.effectRubMonth)}</span>
              <span className="ml-2 text-lg">в месяц</span>
            </div>
            <p className="mt-2 text-ink-2">
              Скорее всего — от {rub(e.result.ciLow)} до {rub(e.result.ciHigh)} в месяц. Ждали {rub(e.expectedRubMonth)}.
            </p>
            <EffectRange low={e.result.ciLow} high={e.result.ciHigh} value={e.result.effectRubMonth} expected={e.expectedRubMonth} />
            <p className="mt-4 text-sm text-ink-2">{e.result.text.replace(" (разница разниц)", "")}</p>
            {e.result.rolloutRubMonth && (
              <div className="mt-5 flex flex-wrap items-center gap-3 rounded-[16px] bg-surface p-4">
                <span className="text-sm">
                  Если ввести во всех ресторанах: еще <span className="font-semibold text-gain">+{perMonth(e.result.rolloutRubMonth)}</span>
                </span>
                {rollouts.includes(e.id) ? (
                  <span className="text-sm font-medium text-gain">Отправлено на утверждение</span>
                ) : (
                  <Button variant="primary" onClick={() => proposeRollout(e.id)}>
                    Предложить всем ресторанам
                  </Button>
                )}
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
              <RestaurantChips codes={e.test} tone="test" />
            </div>
            <div className="grid place-items-center text-sm text-ink-3">сравниваем с</div>
            <div className="rounded-[16px] bg-paper p-4">
              <div className="mb-2 text-sm font-medium">С чем сравниваем</div>
              <RestaurantChips codes={e.control} tone="control" />
              {!e.control.length && <div className="mt-1 text-xs text-ink-3">{e.design.split(":")[1]?.trim()}</div>}
            </div>
          </div>
          <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-3">Что считаем успехом</dt>
              <dd className="mt-0.5 font-medium">{e.metric}</dd>
            </div>
            <div>
              <dt className="text-ink-3">С каким периодом сравниваем</dt>
              <dd className="mt-0.5 font-medium">{e.baseline}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Сколько ждем</dt>
              <dd className="mt-0.5 font-medium">{e.period}</dd>
            </div>
          </dl>
          {e.progress && stage === "running" && <div className="mt-5 rounded-[12px] bg-info-soft p-3 text-sm text-info">{e.progress}</div>}
        </QuestionBlock>
      </Reveal>

      {stage === "proposed" && (
        <Reveal index={3}>
          <QuestionBlock
            question="Что будет после утверждения?"
            answer={`Директорам ${names(e.test).join(", ")} придут задачи со сроком и чек-листом. Замер начнется автоматически.`}
          >
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" size="lg" onClick={() => decideExperiment(e.id, "approved")}>
                Утвердить и поставить задачи
              </Button>
              <Button size="lg" onClick={() => decideExperiment(e.id, "rejected")}>
                Отклонить
              </Button>
            </div>
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

const DURATIONS = [
  { weeks: 2, note: "быстро, но вывод будет менее надежным" },
  { weeks: 4, note: "оптимально для 3 ресторанов" },
  { weeks: 6, note: "надежнее, если продажи сильно скачут" },
];

export function NewCheckPage() {
  const { findingId } = useParams({ from: "/app/checks/new/$findingId" });
  const f = findingById(findingId);
  const navigate = useNavigate();
  const { sendDraft } = usePrototype();
  const [step, setStep] = useState(0);
  const [action, setAction] = useState(0);
  const [control, setControl] = useState<string[]>(() => RESTAURANTS.map((r) => r.code).filter((c) => c !== f?.restaurantId));
  const [weeks, setWeeks] = useState(1);
  if (!f || !f.restaurantId) return <EmptyState title="Находка не найдена" />;
  const expected = Math.round(((f.effectRubMonth ?? 0) * 0.6) / 100) * 100;
  const steps = ["Что меняем", "Где пробуем", "Сколько ждем"];

  return (
    <div className="mx-auto max-w-[760px]">
      <Link to="/findings/$findingId" params={{ findingId: f.id }} className="mb-4 inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> {f.title}
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
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ duration: 0.25, ease: EASE }}
          >
            {step === 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 font-medium">
                  Что меняем в ресторане <AiBadge basis="Варианты мер — из находки и библиотеки типовых мер сети." />
                </div>
                {f.actions.map((a, i) => (
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
                    <RestaurantChips codes={[f.restaurantId]} tone="test" />
                  </div>
                  <p className="mt-2 text-sm text-ink-3">Там, где нашли проблему.</p>
                </div>
                <div>
                  <div className="flex items-center gap-2 font-medium">
                    С чем сравниваем <Sparkles size={14} className="text-brand" />
                  </div>
                  <p className="mt-1 text-sm text-ink-3">Су-шеф выбрал похожие рестораны, где ничего не будем менять. Снимите галочку, если ресторан не подходит.</p>
                  <div className="mt-3 space-y-2">
                    {RESTAURANTS.filter((r) => r.code !== f.restaurantId).map((r) => (
                      <label key={r.code} className="flex items-center gap-3 rounded-[12px] border border-line p-3">
                        <input
                          type="checkbox"
                          checked={control.includes(r.code)}
                          onChange={() => setControl((c) => (c.includes(r.code) ? c.filter((x) => x !== r.code) : [...c, r.code]))}
                          className="h-4 w-4 accent-[#0a8f84]"
                        />
                        <span className="font-medium">{r.name}</span>
                        <span className="ml-auto text-xs text-ink-3">похожая выручка и меню</span>
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
                    {DURATIONS.map((d, i) => (
                      <button
                        key={d.weeks}
                        type="button"
                        onClick={() => setWeeks(i)}
                        className={cx("rounded-[12px] border p-3 text-left", weeks === i ? "border-brand bg-brand-soft" : "border-line")}
                      >
                        <div className="font-semibold">{d.weeks} недели</div>
                        <div className="text-xs text-ink-3">{d.note}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded-[14px] bg-paper p-4 text-sm">
                  <div className="font-medium">Что считаем успехом</div>
                  <div className="mt-1 text-ink-2">
                    «{f.scale?.label ?? f.metric.label}» приблизится к {f.scale?.network !== undefined ? "уровню сети" : "норме"}. Ожидаем +{perMonth(expected)} — это
                    60% от найденного, оценка с запасом.
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </Card>

      <Card className="mt-4 p-5 text-sm">
        <div className="mb-1 font-medium">Итог</div>
        <div className="text-ink-2">
          {f.actions[action]} — в ресторане «{restaurantByCode(f.restaurantId)?.name}», сравниваем с {control.length ? names(control).join(", ") : "показателями внутри ресторана"},{" "}
          {DURATIONS[weeks]!.weeks} недели. Директор получит задачу после утверждения.
        </div>
        <div className="mt-1">
          <VerifiedNote>ожидаемый эффект по данным находки</VerifiedNote>
        </div>
      </Card>

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
            onClick={() => {
              sendDraft(f.id);
              void navigate({ to: "/decisions" });
            }}
          >
            Отправить на утверждение
          </Button>
        )}
      </div>
    </div>
  );
}
