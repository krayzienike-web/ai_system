import { Link } from "@tanstack/react-router";
import { ArrowDownRight, ArrowUpRight, CheckCircle2, MessageCircle, PackageX, TrendingUp } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useState } from "react";

import { AiBadge, VerifiedNote } from "../../ds/ai";
import { Button, Card, cx, EmptyState, QuestionBlock, Reveal, Term } from "../../ds/primitives";
import { AnimatedNumber, BulletScale, ProcessMap } from "../../ds/viz";
import { pct, perMonth, points, rub, thousands } from "../../lib/format";
import { DIGEST_SOURCES, DIGEST_TEXT, IMPROVEMENTS, KPIS, ON_TABLE_LAST_WEEK, PERIOD, STOCK_RISKS } from "../../mock/data";
import {
  networkKpis,
  PROCESSES,
  processStatus,
  processTitle,
  restaurantByCode,
  findingById,
  restaurantFindings,
  weeklyActions,
} from "../../mock/selectors";
import type { Finding, ProcessKey } from "../../mock/types";
import { usePrototype } from "../../state/prototype";
import { useTasks } from "../counts";
import { ActionCard, FindingRow, TakeToWorkDialog, useStatus } from "../findings/parts";

/** The weekly view of one restaurant. Director's home; HQ opens it from "Рестораны" (readOnly). */
export function WeekView({ code, readOnly = false }: { code: string; readOnly?: boolean }) {
  const { openChat, findingStatus, notify } = usePrototype();
  const [taking, setTaking] = useState<Finding | null>(null);
  const [process, setProcess] = useState<ProcessKey | null>(null);
  const tasks = useTasks();
  const restaurant = restaurantByCode(code);
  if (!restaurant) return <EmptyState title="Ресторан не найден" />;

  const { problems, opportunities, losses, potential } = restaurantFindings(code);
  const onTable = losses + potential;
  const lastWeek = ON_TABLE_LAST_WEEK[code] ?? onTable;
  const delta = onTable - lastWeek;
  const actions = weeklyActions(code, 5)
    .filter((f) => (findingStatus[f.id] ?? f.status) === "new")
    .slice(0, 3);
  const all = [...problems, ...opportunities];
  const listed = process ? all.filter((f) => f.process === process) : all;
  const tiles = PROCESSES.map((p) => {
    const s = processStatus(code, p.key);
    return { key: p.key, title: p.title, status: s.status, losses: s.losses, detail: perMonth(s.losses) };
  });
  const worst = [...tiles].sort((a, b) => processStatus(code, b.key).losses - processStatus(code, a.key).losses)[0]!;
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
              {restaurant.name} · неделя {PERIOD.week}
            </div>
            <div className="mt-4 text-sm font-medium text-spark">
              <Term hint="Сколько прибыли в месяц можно добавить: перестать терять деньги на перерасходе, переплатах и списаниях — и дополнительно заработать на ценах меню и лучших поставщиках">Можно добавить к прибыли</Term>
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-display text-[56px] leading-none font-semibold tracking-tight sm:text-[72px]">
                <AnimatedNumber value={onTable} format={thousands} />
              </span>
              <span className="text-lg text-white/80">тыс ₽ в месяц</span>
            </div>
            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <span>
                <span className="text-white/60">= перестать терять </span>
                <span className="num font-semibold">{rub(losses)}</span>
              </span>
              <span>
                <span className="text-white/60">+ дополнительно заработать </span>
                <span className="num font-semibold">{rub(potential)}</span>
              </span>
            </div>
            <div
              className={cx(
                "mt-5 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm",
                delta <= 0 ? "bg-gain-icon/20 text-[#9be3a9]" : "bg-loss-icon/25 text-[#ffb4ad]",
              )}
            >
              {delta <= 0 ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />}
              {delta <= 0
                ? `На ${rub(-delta)} меньше, чем неделю назад — потери сокращаются`
                : `На ${rub(delta)} больше, чем неделю назад`}
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

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-6">
          {/* 3. Where the money is lost */}
          <Reveal index={2}>
            <QuestionBlock
              question="Где ресторан теряет деньги?"
              answer={
                <>
                  Больше всего — в процессе «{worst.title}»: <span className="text-loss">{worst.detail}</span>.{" "}
                  <span className="text-ink-3">Нажмите на процесс, чтобы увидеть его находки.</span>
                </>
              }
              source={<VerifiedNote>открытые находки на {PERIOD.dataUntil}</VerifiedNote>}
            >
              <ProcessMap tiles={tiles} selected={process} onSelect={setProcess} />
              <div className="mt-5 border-t border-line pt-3">
                <div className="mb-1 flex items-center justify-between px-3 text-sm">
                  <span className="font-medium">
                    {process ? `Находки: ${processTitle(process)}` : `Все находки ресторана · ${all.length}`}
                  </span>
                  {process && (
                    <button type="button" className="text-brand-strong hover:underline" onClick={() => setProcess(null)}>
                      Показать все
                    </button>
                  )}
                </div>
                {listed.length ? (
                  listed.map((f) => <FindingRow key={f.id} f={f} />)
                ) : (
                  <div className="px-3 py-4 text-sm text-ink-3">В этом процессе все в норме — потерь не нашли.</div>
                )}
              </div>
            </QuestionBlock>
          </Reveal>

          {/* 4. Me vs network */}
          <Reveal index={3}>
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
        </div>

        <aside className="space-y-6">
          <Reveal index={4}>
            <QuestionBlock
              question="Что может закончиться?"
              answer={risks.length ? `${risks.length} позиции под риском до ближайшей поставки` : "Рисков на ближайшие дни нет"}
            >
              <ul className="space-y-3">
                {risks.map((r) => {
                  const gap = r.nextDeliveryInDays - r.daysLeft;
                  return (
                    <li key={r.product} className="rounded-[12px] bg-paper p-3">
                      <div className="flex items-center gap-2 font-medium">
                        <PackageX size={16} className={gap > 0 ? "text-loss" : "text-warn"} aria-hidden />
                        {r.product}
                      </div>
                      <div className="mt-1 text-sm text-ink-2">
                        {gap > 0
                          ? `Закончится за ${gap} дн. до поставки`
                          : "Закончится в день поставки — впритык"}
                      </div>
                      <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-ink/10" aria-hidden>
                        <div className="bg-brand" style={{ width: `${(r.daysLeft / r.nextDeliveryInDays) * 100}%` }} />
                      </div>
                      <div className="mt-1 flex justify-between text-[11px] text-ink-3">
                        <span>хватит на {r.daysLeft} дн.</span>
                        <span>поставка через {r.nextDeliveryInDays} дн.</span>
                      </div>
                      {!readOnly && (
                        <Button size="sm" className="mt-2.5" onClick={() => notify(`Закупщик предупрежден: ${r.product}, ${r.supplier}`)}>
                          Предупредить закупщика
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </QuestionBlock>
          </Reveal>

          <Reveal index={5}>
            <QuestionBlock question="Что улучшилось?" answer={doneTasks.length ? "Ваши действия уже дают результат" : undefined}>
              <ul className="space-y-3 text-sm">
                {doneTasks.map((t) => (
                  <li key={t.id} className="flex gap-2">
                    <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-gain" aria-hidden />
                    <span>
                      {t.title}
                      {t.result && <span className="block font-medium text-gain">{t.result}</span>}
                    </span>
                  </li>
                ))}
                {IMPROVEMENTS.filter((i) => i.restaurantId === code).map((i) => (
                  <li key={i.text} className="flex gap-2">
                    <TrendingUp size={17} className="mt-0.5 shrink-0 text-gain" aria-hidden />
                    {i.text}
                  </li>
                ))}
              </ul>
            </QuestionBlock>
          </Reveal>

          <Reveal index={6}>
            <Card className="p-5 text-sm text-ink-2">
              <div className="font-medium text-ink">Следующая инвентаризация — {PERIOD.nextInventory}</div>
              После нее пересчитаем потери по техкартам и покажем результат ваших задач в рублях.
            </Card>
          </Reveal>
        </aside>
      </div>

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
