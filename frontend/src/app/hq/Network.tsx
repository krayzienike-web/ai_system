import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDownRight, ArrowUpRight, Inbox } from "lucide-react";

import { useNetworkOverview } from "../../api/hooks";
import type { ApiFinding } from "../../api/types";
import { VerifiedNote } from "../../ds/ai";
import { buttonClass, LoadError, QuestionBlock, Reveal, Skeleton, Term } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend, PROCESS_ICON, ProfitSplit, RankList } from "../../ds/viz";
import { ddmm, money, pct, perMonth, plural, rub, thousands } from "../../lib/format";
import { ProcessMatrix } from "./ProcessMatrix";
import { useUi } from "../../state/ui";

export function NetworkPage() {
  const navigate = useNavigate();
  const { period } = useUi();
  const overview = useNetworkOverview(period);
  const n = overview.data;
  if (overview.isError) return <LoadError error={overview.error} />;
  if (!n) return <Skeleton className="h-[600px]" />;

  const losses = money(n.losses) ?? 0;
  const potential = money(n.potential) ?? 0;
  const onTable = money(n.on_table) ?? 0;
  const trend = n.trend.on_table.map((v) => money(v) ?? 0);
  const change = money(n.trend.change);
  const inbox = n.checks_waiting + n.overdue_tasks;
  const ranking = n.ranking.map((r) => ({
    id: r.code,
    title: r.name,
    value: money(r.losses) ?? 0,
    valueLabel: rub(money(r.losses) ?? 0),
    delta: money(r.delta) ?? undefined,
    sub: r.top_problem ? `Больше всего: ${r.top_problem.toLowerCase()}` : "Проблем выше нормы нет",
    onClick: () => void navigate({ to: "/restaurants/$code", params: { code: r.code } }),
  }));

  return (
    <div className="space-y-6">
      <Reveal>
        <section className="grid gap-6 rounded-[24px] bg-ink p-6 text-white sm:p-8 lg:grid-cols-[1fr_1fr]">
          <div>
            <div className="text-sm text-white/70">Сеть из {plural(n.restaurants, ["ресторана", "ресторанов", "ресторанов"])}</div>
            <div className="mt-4 flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium text-spark">
                <Term hint="Сумма по всем открытым находкам: насколько вырастет прибыль в месяц, если устранить потери и использовать найденные возможности. Оценка до уровня лучших в сети, а не до идеала">Найденный потенциал прибыли</Term>
              </span>
              <Link to="/findings" className="text-white/60 hover:text-white hover:underline">
                в {plural(n.found_count, ["находке", "находках", "находках"])} →
              </Link>
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-display text-[56px] leading-none font-semibold tracking-tight sm:text-[72px]">
                <AnimatedNumber value={onTable} format={thousands} />
              </span>
              <span className="text-lg text-white/80">тыс ₽ в месяц</span>
            </div>
            <div className="mt-2 text-sm text-white/60">{rub(money(n.on_table_year) ?? 0)} в год</div>
            <ProfitSplit losses={losses} missed={potential} format={rub} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <div className="rounded-[18px] bg-white/[0.07] p-5">
              <div className="text-sm text-white/70">Подтвержденный эффект</div>
              <div className="mt-1 font-display text-3xl font-semibold text-[#9be3a9]">
                +<AnimatedNumber value={money(n.confirmed) ?? 0} format={thousands} /> <span className="text-base text-white/80">тыс ₽</span>
              </div>
              <div className="mt-1 text-xs text-white/60">
                в месяц — прибыль, которую уже дали изменения. Завершено проверок: {n.completed_checks}
              </div>
            </div>
            <Link to="/decisions" className="group rounded-[18px] bg-spark p-5 text-ink transition hover:brightness-105">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Inbox size={16} /> Ждут вашего решения
              </div>
              <div className="mt-1 font-display text-3xl font-semibold">{inbox}</div>
              <div className="mt-1 text-xs text-ink/70">
                {[
                  n.checks_waiting && plural(n.checks_waiting, ["проверка ждет запуска", "проверки ждут запуска", "проверок ждут запуска"]),
                  n.overdue_tasks && plural(n.overdue_tasks, ["просроченная задача", "просроченные задачи", "просроченных задач"]),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
              <div className="mt-2 text-xs font-medium group-hover:underline">Перейти к решениям →</div>
            </Link>
          </div>
        </section>
      </Reveal>

      {n.kpi && (
        <Reveal index={1}>
          <dl className="grid gap-3 sm:grid-cols-3">
            {[
              {
                label: "Фудкост сети",
                value: n.kpi.food_cost_actual !== null ? pct((money(n.kpi.food_cost_actual) ?? 0) * 100) : "—",
                note:
                  n.kpi.food_cost_theory !== null
                    ? `по техкартам — ${pct((money(n.kpi.food_cost_theory) ?? 0) * 100)}; ${ddmm(n.kpi.food_cost_from)}–${ddmm(n.kpi.food_cost_to)}`
                    : "",
              },
              {
                label: "Списания",
                value: n.kpi.write_offs_share !== null ? pct((money(n.kpi.write_offs_share) ?? 0) * 100, 2) : "—",
                note: n.kpi.write_offs_from ? `доля выручки; ${ddmm(n.kpi.write_offs_from)}–${ddmm(n.kpi.write_offs_to)}` : "доля выручки",
              },
              {
                label: "Переплаты поставщикам",
                value: perMonth(money(n.overpay) ?? 0),
                note: "открытые находки по закупкам",
              },
            ].map((k) => (
              <div key={k.label} className="rounded-[16px] border border-line bg-surface p-4">
                <dt className="text-sm text-ink-3">{k.label}</dt>
                <dd className="num mt-1 font-display text-2xl font-semibold">{k.value}</dd>
                {k.note && <dd className="mt-0.5 text-xs text-ink-3">{k.note}</dd>}
              </div>
            ))}
          </dl>
        </Reveal>
      )}

      <Reveal index={2}>
        <QuestionBlock question="Где именно теряем?" answer={n.matrix_answer} source={<VerifiedNote>открытые проверенные находки ресторанов, ₽ в месяц; сетевые находки — в «Общих проблемах сети»</VerifiedNote>}>
          <ProcessMatrix n={n} />
        </QuestionBlock>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-2">
        <Reveal index={3}>
          <QuestionBlock
            question="Сокращаются ли потери сети?"
            answer={n.trend.answer}
            source={<VerifiedNote>оценка на конец каждой недели</VerifiedNote>}
            className="h-full"
          >
            <AreaTrend
              labels={n.trend.labels}
              series={[{ name: "Найденный потенциал", values: trend, color: "#0a8f84", fill: true }]}
              format={(v) => rub(v)}
              height={150}
            />
            {/* No change: the answer above already says «не изменился», an arrow «на 0% меньше» would contradict it. */}
            {change !== null && change !== 0 && n.trend.change_pct !== null && (
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className={`inline-flex items-center gap-1.5 font-medium ${change <= 0 ? "text-gain" : "text-loss"}`}>
                  {change <= 0 ? <ArrowDownRight size={15} /> : <ArrowUpRight size={15} />} на {n.trend.change_pct}%{" "}
                  {change <= 0 ? "меньше" : "больше"}, чем {n.trend.span} назад
                </span>
                <span className="text-xs text-ink-3">Линия — потери + упущенная выгода, ₽ в месяц. Чем ниже, тем лучше</span>
              </div>
            )}
          </QuestionBlock>
        </Reveal>

        <Reveal index={4}>
          <QuestionBlock
            question="Кто теряет больше всего?"
            action={
              <Link to="/restaurants" className="text-sm font-medium text-brand-strong hover:underline">
                Все рестораны ({n.restaurants}) →
              </Link>
            }
            answer={
              ranking[0] && ranking[0].value > 0
                ? `${ranking[0].title} — ${perMonth(ranking[0].value)}. Здесь топ-5, полный список с поиском — в «Все рестораны».`
                : "Открытых потерь в ресторанах нет."
            }
            source={<VerifiedNote>открытые проблемы; «лучше / хуже» — по сравнению с прошлой неделей</VerifiedNote>}
            className="h-full"
          >
            <RankList items={ranking.slice(0, 5)} />
          </QuestionBlock>
        </Reveal>
      </div>

      <Reveal index={5}>
        <QuestionBlock
          question="Общие проблемы сети"
          answer={
            n.common.length
              ? `${plural(n.common.length, ["проблема повторяется", "проблемы повторяются", "проблем повторяются"])} в нескольких ресторанах — их выгоднее решать одним решением на всю сеть.`
              : "Общих проблем нет"
          }
        >
          <ul className="divide-y divide-line">
            {n.common.map((c) => {
              const Icon = PROCESS_ICON[c.process as ApiFinding["process"]];
              const value = money(c.losses);
              const row = (
                <>
                  <span className="grid h-9 w-9 place-items-center rounded-[10px] bg-loss-soft text-loss">
                    <Icon size={18} strokeWidth={1.75} />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-medium">{c.title}</span>
                    <span className="block text-sm text-ink-3">{c.where}</span>
                  </span>
                  <span className="text-right text-sm">
                    {value ? <span className="num font-semibold text-loss">{perMonth(value)}</span> : <span className="text-warn">{c.note}</span>}
                  </span>
                </>
              );
              const cls = "grid grid-cols-[36px_1fr_auto] items-center gap-3 rounded-[12px] px-2 py-3 transition hover:bg-paper";
              return (
                <li key={c.key}>
                  {c.finding_id ? (
                    <Link to="/findings/$findingId" params={{ findingId: c.finding_id }} className={cls}>
                      {row}
                    </Link>
                  ) : (
                    <Link to="/findings" className={cls}>
                      {row}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        </QuestionBlock>
      </Reveal>

      <Reveal index={6}>
        <div className="flex flex-wrap gap-3">
          <Link to="/findings" className={buttonClass("secondary")}>
            Все находки сети
          </Link>
          <Link to="/report" className={buttonClass("secondary")}>
            Отчет для руководителя
          </Link>
        </div>
      </Reveal>
    </div>
  );
}
