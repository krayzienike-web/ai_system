import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDownRight, Inbox } from "lucide-react";

import { VerifiedNote } from "../../ds/ai";
import { buttonClass, QuestionBlock, Reveal, Term } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend, PROCESS_ICON, ProfitSplit, RankList } from "../../ds/viz";
import { perMonth, plural, rub, thousands } from "../../lib/format";
import { EXPERIMENTS, FINDINGS, LOSSES_LAST_WEEK, RESTAURANTS } from "../../mock/data";
import { networkTotals, networkTrend, PROCESSES, processStatus, restaurantFindings } from "../../mock/selectors";
import { useInbox } from "../counts";

export function NetworkPage() {
  const navigate = useNavigate();
  const totals = networkTotals();
  const trend = networkTrend();
  const onTable = totals.losses + totals.potential;
  const first = trend.onTable[0]!;
  const inbox = useInbox();
  const completedChecks = EXPERIMENTS.filter((e) => e.result).length;
  const inboxCount = inbox.experiments.length + inbox.overdue.length + inbox.drafts.length;

  const ranking = RESTAURANTS.map((r) => {
    const { losses, problems } = restaurantFindings(r.code);
    const top = problems[0];
    return {
      id: r.code,
      title: r.name,
      value: losses,
      valueLabel: rub(losses),
      delta: losses - (LOSSES_LAST_WEEK[r.code] ?? losses),
      sub: top ? `Больше всего: ${top.title.toLowerCase()}` : "Проблем выше нормы нет",
      onClick: () => void navigate({ to: "/restaurants/$code", params: { code: r.code } }),
    };
  }).sort((a, b) => b.value - a.value);

  const systemic = PROCESSES.map((p) => {
    const hit = RESTAURANTS.filter((r) => processStatus(r.code, p.key).status !== "good");
    const losses = hit.reduce((acc, r) => acc + processStatus(r.code, p.key).losses, 0);
    return { ...p, hit, losses };
  })
    .filter((p) => p.hit.length >= 2);
  // One list: a process failing in several restaurants and a finding that is network-wide by nature are the same kind of problem.
  const common = [
    ...FINDINGS.filter((f) => f.restaurantId === null).map((f) => ({
      key: f.id,
      process: f.process,
      title: f.title,
      where: "Во всех ресторанах",
      losses: f.effectRubMonth ?? 0,
      note: f.effectNote ?? "сумму пока не оценить",
      findingId: f.id as string | undefined,
    })),
    ...systemic.map((p) => ({
      key: p.key,
      process: p.key,
      title: `${p.title}: проблемы в ${plural(p.hit.length, ["ресторане", "ресторанах", "ресторанах"])}`,
      where: p.hit.map((r) => r.name.replace("Ресторан ", "")).join(", "),
      losses: p.losses,
      note: "пробел в данных",
      findingId: undefined as string | undefined,
    })),
  ].sort((a, b) => b.losses - a.losses);

  return (
    <div className="space-y-6">
      <Reveal>
        <section className="grid gap-6 rounded-[24px] bg-ink p-6 text-white sm:p-8 lg:grid-cols-[1fr_1fr]">
          <div>
            <div className="text-sm text-white/70">
              Сеть из {plural(RESTAURANTS.length, ["ресторана", "ресторанов", "ресторанов"])}
            </div>
            <div className="mt-4 text-sm font-medium text-spark">
              <Term hint="Насколько вырастет прибыль в месяц, если устранить потери и использовать найденные возможности. Оценка до уровня лучших в сети, а не до идеала">Потенциал прибыли сети</Term>
            </div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-display text-[56px] leading-none font-semibold tracking-tight sm:text-[72px]">
                <AnimatedNumber value={onTable} format={thousands} />
              </span>
              <span className="text-lg text-white/80">тыс ₽ в месяц</span>
            </div>
            <div className="mt-2 text-sm text-white/60">{rub(onTable * 12)} в год</div>
            <ProfitSplit losses={totals.losses} missed={totals.potential} format={rub} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <div className="rounded-[18px] bg-white/[0.07] p-5">
              <div className="text-sm text-white/70">Подтвержденный эффект</div>
              <div className="mt-1 font-display text-3xl font-semibold text-[#9be3a9]">
                +<AnimatedNumber value={totals.confirmed} format={thousands} /> <span className="text-base text-white/80">тыс ₽</span>
              </div>
              <div className="mt-1 text-xs text-white/60">
                в месяц — прибыль, которую уже дали изменения. Завершено проверок: {completedChecks}
              </div>
            </div>
            <Link to="/decisions" className="group rounded-[18px] bg-spark p-5 text-ink transition hover:brightness-105">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Inbox size={16} /> Ждут вашего решения
              </div>
              <div className="mt-1 font-display text-3xl font-semibold">{inboxCount}</div>
              <div className="mt-1 text-xs text-ink/70">
                {[
                  inbox.experiments.length && plural(inbox.experiments.length, ["проверка ждет запуска", "проверки ждут запуска", "проверок ждут запуска"]),
                  inbox.overdue.length && plural(inbox.overdue.length, ["просроченная задача", "просроченные задачи", "просроченных задач"]),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
              <div className="mt-2 text-xs font-medium group-hover:underline">Перейти к решениям →</div>
            </Link>
          </div>
        </section>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-2">
        <Reveal index={1}>
          <QuestionBlock
            question="Сокращаются ли потери сети?"
            answer={
              <>
                Да. Сумма, которую сеть теряет и недозарабатывает, за 8 недель снизилась с {rub(first)} до {rub(onTable)} в месяц — часть проблем уже исправили.
              </>
            }
            source={<VerifiedNote>оценка на конец каждой недели</VerifiedNote>}
            className="h-full"
          >
            <AreaTrend
              labels={trend.labels}
              series={[{ name: "Потенциал прибыли", values: trend.onTable, color: "#0a8f84", fill: true }]}
              format={(n) => rub(n)}
              height={150}
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="inline-flex items-center gap-1.5 font-medium text-gain">
                <ArrowDownRight size={15} /> на {Math.round((1 - onTable / first) * 100)}% меньше, чем 8 недель назад
              </span>
              <span className="text-xs text-ink-3">Линия — потери + упущенная выгода, ₽ в месяц. Чем ниже, тем лучше</span>
            </div>
          </QuestionBlock>
        </Reveal>

        <Reveal index={2}>
          <QuestionBlock
            question="Кто теряет больше всего?"
            action={
              <Link to="/restaurants" className="text-sm font-medium text-brand-strong hover:underline">
                Все рестораны ({RESTAURANTS.length}) →
              </Link>
            }
            answer={
              <>
                {ranking[0]!.title} — {perMonth(ranking[0]!.value)}. Здесь топ-5, полный список с поиском — в «Все рестораны».
              </>
            }
            source={<VerifiedNote>открытые проблемы; «лучше / хуже» — по сравнению с прошлой неделей</VerifiedNote>}
            className="h-full"
          >
            <RankList items={ranking.slice(0, 5)} />
          </QuestionBlock>
        </Reveal>
      </div>

      <Reveal index={3}>
        <QuestionBlock
          question="Общие проблемы сети"
          answer={
            common.length
              ? `${plural(common.length, ["проблема повторяется", "проблемы повторяются", "проблем повторяются"])} в нескольких ресторанах — их выгоднее решать одним решением на всю сеть.`
              : "Общих проблем нет"
          }
        >
          <ul className="divide-y divide-line">
            {common.map((c) => {
              const Icon = PROCESS_ICON[c.process];
              return (
                <li key={c.key}>
                  <Link
                    to={c.findingId ? "/findings/$findingId" : "/findings"}
                    params={c.findingId ? { findingId: c.findingId } : undefined}
                    className="grid grid-cols-[36px_1fr_auto] items-center gap-3 rounded-[12px] px-2 py-3 transition hover:bg-paper"
                  >
                    <span className="grid h-9 w-9 place-items-center rounded-[10px] bg-loss-soft text-loss">
                      <Icon size={18} strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0">
                      <span className="block font-medium">{c.title}</span>
                      <span className="block text-sm text-ink-3">{c.where}</span>
                    </span>
                    <span className="text-right text-sm">
                      {c.losses ? <span className="num font-semibold text-loss">{perMonth(c.losses)}</span> : <span className="text-warn">{c.note}</span>}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </QuestionBlock>
      </Reveal>

      <Reveal index={4}>
        <div className="flex flex-wrap gap-3">
          <Link to="/findings" className={buttonClass("secondary")}>
            Все находки сети
          </Link>
          <Link to="/report" className={buttonClass("secondary")}>
            Отчет для собственника
          </Link>
        </div>
      </Reveal>
    </div>
  );
}
