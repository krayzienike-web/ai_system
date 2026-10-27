import { Link } from "@tanstack/react-router";
import { ArrowDownRight, ArrowUpRight, CheckCircle2, ChevronDown, MessageCircle } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useState } from "react";

import { useAppContext, useRestaurantWeek } from "../../api/hooks";
import type { ApiFinding } from "../../api/types";
import { VerifiedNote } from "../../ds/ai";
import { Card, cx, EmptyState, QuestionBlock, Reveal, Skeleton, Term } from "../../ds/primitives";
import { AnimatedNumber, BulletScale, PROCESS_ICON, ProfitSplit } from "../../ds/viz";
import { ddmm, money, pct, perMonth, plural, rub, thousands } from "../../lib/format";
import { useUi } from "../../state/ui";
import { ActionCard, FindingRow, MoneyWords, TakeToWorkDialog } from "../findings/parts";
import { OutcomePill } from "../tasks/trace";

const share = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v) * 100);

/** The weekly view of one restaurant. Director's home; HQ opens it from "Рестораны" (readOnly). */
export function WeekView({ code, readOnly = false }: { code: string; readOnly?: boolean }) {
  const { openChat } = useUi();
  const week = useRestaurantWeek(code);
  const context = useAppContext();
  const [taking, setTaking] = useState<ApiFinding | null>(null);
  const [process, setProcess] = useState<string | null>(null);
  if (week.isError) return <EmptyState title="Ресторан не найден" />;
  const w = week.data;
  if (!w) return <Skeleton className="h-[600px]" />;

  const losses = money(w.losses) ?? 0;
  const potential = money(w.potential) ?? 0;
  const delta = money(w.delta_week);
  const nextCount = ddmm(context.data?.next_count_on);
  const me = w.kpi;
  const net = w.network_kpi;
  const maxLoss = Math.max(...w.processes.map((p) => money(p.losses) ?? 0), 1);

  return (
    <div className="space-y-6">
      {/* 1. Hero: how much can be returned, vs last week, and the summary */}
      <Reveal>
        <section className="grid gap-6 overflow-hidden rounded-[24px] bg-ink p-6 text-white sm:p-8 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <div className="text-sm text-white/70">{w.restaurant.name}</div>
            <div className="mt-4 flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium text-spark">
                <Term hint="Сумма по всем открытым находкам: насколько вырастет прибыль в месяц, если устранить потери и использовать найденные возможности. Оценка до уровня лучших в сети, а не до идеала">Найденный потенциал прибыли</Term>
              </span>
              <Link to="/findings" className="text-white/60 hover:text-white hover:underline">
                в {plural(w.found_count, ["находке", "находках", "находках"])} →
              </Link>
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-display text-[56px] leading-none font-semibold tracking-tight sm:text-[72px]">
                <AnimatedNumber value={losses + potential} format={thousands} />
              </span>
              <span className="text-lg text-white/80">тыс ₽ в месяц</span>
            </div>
            <ProfitSplit losses={losses} missed={potential} format={rub} />
            {delta !== null && delta !== 0 && (
              <div
                className={cx(
                  "mt-5 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm",
                  delta < 0 ? "bg-gain-icon/20 text-[#9be3a9]" : "bg-loss-icon/25 text-[#ffb4ad]",
                )}
              >
                {delta < 0 ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />}
                {delta < 0
                  ? `За неделю найденный потенциал снизился на ${rub(-delta)}: часть проблем уже решена`
                  : `За неделю найденный потенциал вырос на ${rub(delta)}: появились новые проблемы`}
              </div>
            )}
          </div>
          <div className="flex flex-col rounded-[18px] bg-white/[0.06] p-5">
            <div className="text-sm font-medium">Главное за неделю</div>
            <p className="mt-3 flex-1 text-[15px] leading-relaxed text-white/90">{w.digest}</p>
            {w.digest_findings.length > 0 && (
              <div className="mt-3">
                <div className="text-xs text-white/50">На чем основан текст:</div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {w.digest_findings.map((f) => (
                    <Link
                      key={f.id}
                      to="/findings/$findingId"
                      params={{ findingId: f.id }}
                      className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-white/90 hover:bg-white/20"
                    >
                      {f.title} →
                    </Link>
                  ))}
                </div>
              </div>
            )}
            <button
              type="button"
              onClick={() => openChat({ title: `Неделя: ${w.restaurant.name}` })}
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
            {w.top.map((f, i) => (
              <Card key={f.id} className="p-5">
                <div className="font-display text-sm font-semibold text-ink-3">Дело {i + 1}</div>
                <Link to="/findings/$findingId" params={{ findingId: f.id }} className="mt-2 block font-semibold hover:underline">
                  {f.title}
                </Link>
                <div className="mt-1 text-sm">
                  <MoneyWords f={f} />
                  <span className="text-ink-3"> · {f.work.stage === "new" ? "директор еще не взял" : "в работе"}</span>
                </div>
              </Card>
            ))}
          </div>
        ) : w.actions.length ? (
          <div className="grid gap-4 md:grid-cols-3">
            <AnimatePresence mode="popLayout">
              {w.actions.map((f, i) => (
                <ActionCard key={f.id} f={f} index={i} onTake={() => setTaking(f)} />
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <EmptyState title="Все главные дела недели уже в работе">
            Отлично. Следите за выполнением в «Задачах»{nextCount && ` — результат посчитаем после инвентаризации ${nextCount}`}.
          </EmptyState>
        )}
      </Reveal>

      {/* 3. Where the money is lost: processes ranked by money, findings open in place */}
      <Reveal index={3}>
        <QuestionBlock
          question="Где ресторан теряет деньги?"
          answer={
            w.processes.length ? (
              <>
                Потери есть в {plural(w.processes.length, ["процессе", "процессах", "процессах"])} из {w.processes.length + w.fine_processes.length}. Больше всего —{" "}
                «{w.processes[0]!.title}»: <span className="text-loss">{perMonth(money(w.processes[0]!.losses) ?? 0)}</span>.
              </>
            ) : (
              "Потерь выше нормы не нашли"
            )
          }
          source={context.data?.data_until && <VerifiedNote>открытые находки на {ddmm(context.data.data_until)}</VerifiedNote>}
        >
          <ul className="divide-y divide-line">
            {w.processes.map((p) => {
              const Icon = PROCESS_ICON[p.process as ApiFinding["process"]];
              const open = process === p.process;
              const value = money(p.losses) ?? 0;
              return (
                <li key={p.process}>
                  <button
                    type="button"
                    onClick={() => setProcess(open ? null : p.process)}
                    aria-expanded={open}
                    className="grid w-full grid-cols-[36px_1fr_auto] items-center gap-3 rounded-[12px] px-2 py-3 text-left transition hover:bg-paper"
                  >
                    <span className="grid h-9 w-9 place-items-center rounded-[10px] bg-loss-soft text-loss">
                      <Icon size={18} strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="font-medium">{p.title}</span>
                        <span className="num shrink-0 font-semibold text-loss">{perMonth(value)}</span>
                      </span>
                      <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-ink/5">
                        <span className="block h-full rounded-full bg-loss-icon" style={{ width: `${(value / maxLoss) * 100}%` }} />
                      </span>
                      <span className="mt-1 block truncate text-xs text-ink-3">
                        {plural(p.findings.length, ["находка", "находки", "находок"])}: {p.findings.map((f) => f.title).join(" · ")}
                      </span>
                    </span>
                    <ChevronDown size={18} className={cx("text-ink-3 transition", open && "rotate-180")} />
                  </button>
                  {open && (
                    <div className="pb-2 pl-10">
                      {p.findings.map((f) => (
                        <FindingRow key={f.id} f={f} />
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {w.fine_processes.length > 0 && (
            <p className="mt-3 flex items-start gap-2 border-t border-line px-2 pt-3 text-sm text-ink-3">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-gain" aria-hidden />В норме: {w.fine_processes.join(", ")}.
            </p>
          )}
          <Link to="/findings" className="mt-3 inline-block px-2 text-sm font-medium text-brand-strong hover:underline">
            Все находки ресторана, включая возможности заработать →
          </Link>
        </QuestionBlock>
      </Reveal>

      {/* 4. Me vs network */}
      {me && net && (
        <Reveal index={4}>
          <QuestionBlock
            question="Как ресторан выглядит на фоне сети?"
            answer={w.kpi_answer}
            source={
              <VerifiedNote>
                фудкост — период {ddmm(me.food_cost_from)}–{ddmm(me.food_cost_to)}, списания — последние 4 недели; среднее по сети взвешено по выручке
              </VerifiedNote>
            }
          >
            <div className="grid gap-x-8 gap-y-2 md:grid-cols-2">
              {share(me.food_cost_actual) !== null && (
                <div>
                  <div className="text-sm font-medium">Фактический фудкост</div>
                  <BulletScale
                    me={share(me.food_cost_actual)!}
                    network={share(net.food_cost_actual) ?? undefined}
                    norm={share(me.food_cost_theory) ?? undefined}
                    max={40}
                    format={(n) => pct(n)}
                    meLabel={readOnly ? "Ресторан" : "Вы"}
                  />
                  <p className="-mt-2 text-xs text-ink-3">Норма — фудкост по техкартам проданных блюд. Чем ниже, тем лучше.</p>
                </div>
              )}
              {share(me.write_offs_share) !== null && (
                <div>
                  <div className="text-sm font-medium">Списания, % выручки</div>
                  <BulletScale
                    me={share(me.write_offs_share)!}
                    network={share(net.write_offs_share) ?? undefined}
                    max={Math.max(1, (share(me.write_offs_share) ?? 0) * 1.5, (share(net.write_offs_share) ?? 0) * 1.5)}
                    format={(n) => pct(n, 2)}
                    meLabel={readOnly ? "Ресторан" : "Вы"}
                  />
                  <p className="-mt-2 text-xs text-ink-3">Чем ниже, тем лучше.</p>
                </div>
              )}
            </div>
          </QuestionBlock>
        </Reveal>
      )}

      {/* 5. Results of what was done */}
      <Reveal index={5}>
        <QuestionBlock
          question="Что дали ваши задачи?"
          answer={w.results_answer}
          action={
            w.done_tasks.length > 0 &&
            !readOnly && (
              <Link to="/tasks" className="text-sm font-medium text-brand-strong hover:underline">
                История задач →
              </Link>
            )
          }
        >
          {w.done_tasks.length > 0 && (
            <ul className="divide-y divide-line">
              {w.done_tasks.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 text-sm">
                  <span className="min-w-0">
                    <span className="block font-medium">{t.title}</span>
                    <span className="block text-xs text-ink-3">
                      сделано {ddmm(t.done_on)}
                      {t.outcome?.text && ` · ${t.outcome.text}`}
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
