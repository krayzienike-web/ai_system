import { Link } from "@tanstack/react-router";
import { ArrowDownRight, ArrowUpRight, CheckCircle2, ChevronDown, MessageCircle, PackageX } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useState } from "react";

import { AiBadge, VerifiedNote } from "../../ds/ai";
import { Button, Card, cx, EmptyState, QuestionBlock, Reveal, Term } from "../../ds/primitives";
import { AnimatedNumber, BulletScale, PROCESS_ICON, ProfitSplit } from "../../ds/viz";
import { pct, perMonth, plural, points, rub, thousands } from "../../lib/format";
import { DIGEST_SOURCES, DIGEST_TEXT, KPIS, ON_TABLE_LAST_WEEK, PERIOD, STOCK_RISKS } from "../../mock/data";
import {
  networkKpis,
  PROCESSES,
  processStatus,
  restaurantByCode,
  findingById,
  restaurantFindings,
  weeklyActions,
} from "../../mock/selectors";
import type { Finding, ProcessKey, Task } from "../../mock/types";
import { usePrototype } from "../../state/prototype";
import { useTasks } from "../counts";
import { OutcomePill } from "../tasks/trace";
import { ActionCard, FindingRow, TakeToWorkDialog, useStatus } from "../findings/parts";

/** The weekly view of one restaurant. Director's home; HQ opens it from "Рестораны" (readOnly). */
export function WeekView({ code, readOnly = false }: { code: string; readOnly?: boolean }) {
  const { openChat, findingStatus, notify } = usePrototype();
  const [taking, setTaking] = useState<Finding | null>(null);
  const [process, setProcess] = useState<ProcessKey | null>(null);
  const tasks = useTasks();
  const restaurant = restaurantByCode(code);
  if (!restaurant) return <EmptyState title="Ресторан не найден" />;

  const { problems, losses, potential } = restaurantFindings(code);
  const onTable = losses + potential;
  const lastWeek = ON_TABLE_LAST_WEEK[code] ?? onTable;
  const delta = onTable - lastWeek;
  const actions = weeklyActions(code, 5)
    .filter((f) => (findingStatus[f.id] ?? f.status) === "new")
    .slice(0, 3);
  const byProcess = PROCESSES.map((p) => ({ ...p, losses: processStatus(code, p.key).losses }));
  const lossProcesses = byProcess.filter((p) => p.losses > 0).sort((a, b) => b.losses - a.losses);
  const fineProcesses = byProcess.filter((p) => p.losses === 0);
  const kpi = KPIS[code]!;
  const avg = networkKpis();
  const risks = STOCK_RISKS.filter((r) => r.restaurantId === code);
  const doneTasks = tasks.filter((t) => t.restaurantId === code && t.status === "done");

  return (
    <div className="space-y-6">
      {/* 1. Hero: how much can be returned, vs last week, and the AI's summary */}
      <Reveal>
        <section className="grid gap-6 overflow-hidden rounded-[24px] bg-ink p-6 text-white sm:p-8 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <div className="text-sm text-white/70">
              {restaurant.name}
            </div>
            <div className="mt-4 text-sm font-medium text-spark">
              <Term hint="Насколько вырастет прибыль в месяц, если устранить потери и использовать найденные возможности. Оценка до уровня лучших в сети, а не до идеала">Потенциал прибыли</Term>
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-display text-[56px] leading-none font-semibold tracking-tight sm:text-[72px]">
                <AnimatedNumber value={onTable} format={thousands} />
              </span>
              <span className="text-lg text-white/80">тыс ₽ в месяц</span>
            </div>
            <ProfitSplit losses={losses} missed={potential} format={rub} />
            <div
              className={cx(
                "mt-5 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm",
                delta <= 0 ? "bg-gain-icon/20 text-[#9be3a9]" : "bg-loss-icon/25 text-[#ffb4ad]",
              )}
            >
              {delta <= 0 ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />}
              {delta <= 0
                ? `За неделю потенциал снизился на ${rub(-delta)}: часть проблем уже решена`
                : `За неделю потенциал вырос на ${rub(delta)}: появились новые проблемы`}
            </div>
          </div>
          <div className="flex flex-col rounded-[18px] bg-white/[0.06] p-5">
            <div className="flex items-center gap-2 text-sm font-medium">
              Главное за неделю <AiBadge basis="Сводка по продажам r_keeper, складу iiko и закупкам 1С за неделю 12–18.10 и последней инвентаризации 01.10." />
            </div>
            <p className="mt-3 flex-1 text-[15px] leading-relaxed text-white/90">{DIGEST_TEXT[code]}</p>
            <div className="mt-3">
              <div className="text-xs text-white/50">На чем основан текст:</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(DIGEST_SOURCES[code] ?? []).map((id) => {
                  const src = findingById(id);
                  return src ? (
                    <Link
                      key={id}
                      to="/findings/$findingId"
                      params={{ findingId: id }}
                      className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-white/90 hover:bg-white/20"
                    >
                      {src.title} →
                    </Link>
                  ) : null;
                })}
              </div>
            </div>
            <button
              type="button"
              onClick={() => openChat({ title: `Неделя: ${restaurant.name}` })}
              className="mt-4 inline-flex w-fit items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-brand-soft"
            >
              <MessageCircle size={15} /> Спросить су-шефа о неделе
            </button>
          </div>
        </section>
      </Reveal>

      {/* 2. Three actions for the week */}
      <Reveal index={1}>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="font-display text-xl font-semibold">С чего начать на этой неделе</h2>
            <p className="text-sm text-ink-3">Три дела, которые дадут больше всего денег при самой надежной оценке</p>
          </div>
          {!readOnly && (
            <Link to="/tasks" className="text-sm font-medium text-brand-strong hover:underline">
              Мои задачи →
            </Link>
          )}
        </div>
        {readOnly ? (
          <div className="grid gap-4 md:grid-cols-3">
            {weeklyActions(code).map((f, i) => (
              <ReadOnlyAction key={f.id} f={f} index={i} />
            ))}
          </div>
        ) : actions.length ? (
          <div className="grid gap-4 md:grid-cols-3">
            <AnimatePresence mode="popLayout">
              {actions.map((f, i) => (
                <ActionCard key={f.id} f={f} index={i} onTake={() => setTaking(f)} />
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <EmptyState title="Все главные дела недели уже в работе">
            Отлично. Следите за выполнением в «Задачах» — результат посчитаем после инвентаризации {PERIOD.nextInventory.slice(0, 5)}.
          </EmptyState>
        )}
      </Reveal>

      {/* 3. Stock that may run out: a slim alert, only when there is something to act on */}
      {risks.length > 0 && (
        <Reveal index={2}>
          <section className="rounded-[18px] border border-warn-icon/40 bg-warn-soft p-4 sm:p-5">
            <div className="flex items-center gap-2 font-medium text-ink">
              <PackageX size={18} className="text-warn" aria-hidden /> Может не хватить до поставки
            </div>
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {risks.map((r) => {
                const gap = r.nextDeliveryInDays - r.daysLeft;
                return (
                  <li key={r.product} className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] bg-surface px-3.5 py-2.5 text-sm">
                    <span>
                      <span className="font-medium">{r.product}</span>
                      <span className="text-ink-2">
                        {" "}
                        — {gap > 0 ? `закончится за ${plural(gap, ["день", "дня", "дней"])} до поставки` : "хватит впритык, до дня поставки"}
                      </span>
                    </span>
                    {!readOnly && (
                      <Button size="sm" onClick={() => notify(`Закупщик предупрежден: ${r.product}, ${r.supplier}`)}>
                        Предупредить закупщика
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        </Reveal>
      )}

      {/* 4. Where the money is lost: processes ranked by money, findings open in place */}
      <Reveal index={3}>
        <QuestionBlock
          question="Где ресторан теряет деньги?"
          answer={
            lossProcesses.length ? (
              <>
                Потери есть в {plural(lossProcesses.length, ["процессе", "процессах", "процессах"])} из {PROCESSES.length}. Больше всего —{" "}
                «{lossProcesses[0]!.title}»: <span className="text-loss">{perMonth(lossProcesses[0]!.losses)}</span>.
              </>
            ) : (
              "Потерь выше нормы не нашли"
            )
          }
          source={<VerifiedNote>открытые находки на {PERIOD.dataUntil}</VerifiedNote>}
        >
          <ul className="divide-y divide-line">
            {lossProcesses.map((p) => {
              const Icon = PROCESS_ICON[p.key];
              const open = process === p.key;
              const items = problems.filter((f) => f.process === p.key);
              return (
                <li key={p.key}>
                  <button
                    type="button"
                    onClick={() => setProcess(open ? null : p.key)}
                    aria-expanded={open}
                    className="grid w-full grid-cols-[36px_1fr_auto] items-center gap-3 rounded-[12px] px-2 py-3 text-left transition hover:bg-paper"
                  >
                    <span className="grid h-9 w-9 place-items-center rounded-[10px] bg-loss-soft text-loss">
                      <Icon size={18} strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="font-medium">{p.title}</span>
                        <span className="num shrink-0 font-semibold text-loss">{perMonth(p.losses)}</span>
                      </span>
                      <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-ink/5">
                        <span className="block h-full rounded-full bg-loss-icon" style={{ width: `${(p.losses / lossProcesses[0]!.losses) * 100}%` }} />
                      </span>
                      <span className="mt-1 block truncate text-xs text-ink-3">
                        {plural(items.length, ["находка", "находки", "находок"])}: {items.map((f) => f.title).join(" · ")}
                      </span>
                    </span>
                    <ChevronDown size={18} className={cx("text-ink-3 transition", open && "rotate-180")} />
                  </button>
                  {open && (
                    <div className="pb-2 pl-10">
                      {items.map((f) => (
                        <FindingRow key={f.id} f={f} />
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {fineProcesses.length > 0 && (
            <p className="mt-3 flex items-start gap-2 border-t border-line px-2 pt-3 text-sm text-ink-3">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-gain" aria-hidden />В норме: {fineProcesses.map((p) => p.title).join(", ")}.
            </p>
          )}
          <Link to="/findings" className="mt-3 inline-block px-2 text-sm font-medium text-brand-strong hover:underline">
            Все находки ресторана, включая возможности заработать →
          </Link>
        </QuestionBlock>
      </Reveal>

      {/* 5. Me vs network */}
      <Reveal index={4}>
        <QuestionBlock
          question="Как ресторан выглядит на фоне сети?"
          answer={
            <>
              Фудкост на {points(kpi.foodCostActual - avg.foodCostActual)} {kpi.foodCostActual >= avg.foodCostActual ? "выше" : "ниже"}{" "}
              среднего по сети, списания — в{" "}
              <span className="num">{(kpi.writeoffsPct / avg.writeoffsPct).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}</span> раза
              больше.
            </>
          }
          source={<VerifiedNote>фудкост — период 03.08–01.10, списания — последние 4 недели; среднее по сети взвешено по выручке</VerifiedNote>}
        >
          <div className="grid gap-x-8 gap-y-2 md:grid-cols-2">
            <div>
              <div className="text-sm font-medium">Фактический фудкост</div>
              <BulletScale me={kpi.foodCostActual} network={avg.foodCostActual} norm={kpi.foodCostTheoretical} max={40} format={(n) => pct(n)} />
              <p className="-mt-2 text-xs text-ink-3">Норма — фудкост по техкартам проданных блюд. Чем ниже, тем лучше.</p>
            </div>
            <div>
              <div className="text-sm font-medium">Списания, % выручки</div>
              <BulletScale me={kpi.writeoffsPct} network={avg.writeoffsPct} max={4} format={(n) => pct(n)} />
              <p className="-mt-2 text-xs text-ink-3">Чем ниже, тем лучше.</p>
            </div>
          </div>
        </QuestionBlock>
      </Reveal>

      {/* 6. Results of what was done */}
      <Reveal index={5}>
        <QuestionBlock
          question="Что дали ваши задачи?"
          answer={improvedAnswer(doneTasks) ?? `Выполненных задач пока нет. Результат в рублях появится после инвентаризации ${PERIOD.nextInventory.slice(0, 5)}.`}
          action={
            doneTasks.length > 0 && !readOnly && (
              <Link to="/tasks" className="text-sm font-medium text-brand-strong hover:underline">
                История задач →
              </Link>
            )
          }
        >
          {doneTasks.length > 0 && (
            <ul className="divide-y divide-line">
              {doneTasks.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 text-sm">
                  <span className="min-w-0">
                    <span className="block font-medium">{t.title}</span>
                    <span className="block text-xs text-ink-3">
                      сделано {t.doneAt} · {t.outcome?.text}
                    </span>
                  </span>
                  <OutcomePill outcome={t.outcome} />
                </li>
              ))}
            </ul>
          )}
        </QuestionBlock>
      </Reveal>

      {taking && <TakeToWorkDialog key={taking.id} f={taking} open onClose={() => setTaking(null)} />}
    </div>
  );
}

function ReadOnlyAction({ f, index }: { f: Finding; index: number }) {
  const status = useStatus(f);
  return (
    <Card className="p-5">
      <div className="font-display text-sm font-semibold text-ink-3">Дело {index + 1}</div>
      <Link to="/findings/$findingId" params={{ findingId: f.id }} className="mt-2 block font-semibold hover:underline">
        {f.title}
      </Link>
      <div className="mt-1 text-sm">
        <span className={f.kind === "problem" ? "text-loss" : "text-gain"}>{perMonth(f.effectRubMonth ?? 0)}</span>
        <span className="text-ink-3"> · {status === "new" ? "директор еще не взял" : "в работе"}</span>
      </div>
    </Card>
  );
}

function improvedAnswer(done: Task[]) {
  if (!done.length) return undefined;
  const confirmed = done.reduce((acc, t) => acc + (t.outcome?.verdict === "confirmed" ? (t.outcome.effectRubMonth ?? 0) : 0), 0);
  const pending = done.filter((t) => t.outcome?.verdict === "pending").length;
  return [confirmed ? `Ваши задачи уже приносят +${perMonth(confirmed)}` : null, pending ? `по ${plural(pending, ["задаче", "задачам", "задачам"])} результат посчитаем после инвентаризации` : null]
    .filter(Boolean)
    .join("; ")
    .replace(/^./, (c) => c.toUpperCase()) + ".";
}
