import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDownRight, Inbox } from "lucide-react";

import { VerifiedNote } from "../../ds/ai";
import { buttonClass, cx, QuestionBlock, Reveal } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend, PROCESS_ICON, RankList } from "../../ds/viz";
import { perMonth, plural, rub, thousands } from "../../lib/format";
import { FINDINGS, LOSSES_LAST_WEEK, PERIOD, RESTAURANTS } from "../../mock/data";
import { networkTotals, networkTrend, PROCESSES, processStatus, restaurantFindings } from "../../mock/selectors";
import { useInbox } from "../counts";
import { FindingRow } from "../findings/parts";

export function NetworkPage() {
  const navigate = useNavigate();
  const totals = networkTotals();
  const trend = networkTrend();
  const onTable = totals.losses + totals.potential;
  const first = trend.onTable[0]!;
  const inbox = useInbox();
  const inboxCount = inbox.experiments.length + inbox.disputed.length + inbox.overdue.length;

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
    .filter((p) => p.hit.length >= 2)
    .sort((a, b) => b.losses - a.losses);
  const networkWide = FINDINGS.filter((f) => f.restaurantId === null);

  return (
    <div className="space-y-6">
      <Reveal>
        <section className="grid gap-6 rounded-[24px] bg-ink p-6 text-white sm:p-8 lg:grid-cols-[1fr_1fr]">
          <div>
            <div className="text-sm text-white/70">
              {plural(RESTAURANTS.length, ["ресторан", "ресторана", "ресторанов"])} · неделя {PERIOD.week}
            </div>
            <div className="mt-4 text-sm font-medium text-spark">Можно вернуть по сети</div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-display text-[56px] leading-none font-semibold tracking-tight sm:text-[72px]">
                <AnimatedNumber value={onTable} format={thousands} />
              </span>
              <span className="text-lg text-white/80">тыс ₽ в месяц</span>
            </div>
            <div className="mt-2 text-sm text-white/60">≈ {rub(onTable * 12)} в год</div>
            <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <span>
                <span className="text-white/60">теряем </span>
                <span className="num font-semibold">{rub(totals.losses)}</span>
              </span>
              <span>
                <span className="text-white/60">можно заработать </span>
                <span className="num font-semibold">{rub(totals.potential)}</span>
              </span>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <div className="rounded-[18px] bg-white/[0.07] p-5">
              <div className="text-sm text-white/70">Уже вернули</div>
              <div className="mt-1 font-display text-3xl font-semibold text-[#9be3a9]">
                <AnimatedNumber value={totals.confirmed} format={thousands} /> <span className="text-base text-white/80">тыс ₽/мес</span>
              </div>
              <div className="mt-1 text-xs text-white/60">подтверждено проверками</div>
            </div>
            <Link to="/decisions" className="group rounded-[18px] bg-spark p-5 text-ink transition hover:brightness-105">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Inbox size={16} /> Ждут вашего решения
              </div>
              <div className="mt-1 font-display text-3xl font-semibold">{inboxCount}</div>
              <div className="mt-1 text-xs text-ink/70 group-hover:underline">Открыть →</div>
            </Link>
          </div>
        </section>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-2">
        <Reveal index={1}>
          <QuestionBlock
            question="Становится ли сеть лучше?"
            answer={
              <>
                Да. За 8 недель сумма, которую можно вернуть, снизилась с {rub(first)} до {rub(onTable)} в месяц.
              </>
            }
            source={<VerifiedNote>оценка на конец каждой недели</VerifiedNote>}
            className="h-full"
          >
            <AreaTrend
              labels={trend.labels}
              series={[{ name: "Можно вернуть", values: trend.onTable, color: "#0a8f84", fill: true }]}
              format={(n) => rub(n)}
              height={150}
            />
            <div className="mt-2 inline-flex items-center gap-1.5 text-sm text-gain">
              <ArrowDownRight size={15} /> −{Math.round((1 - onTable / first) * 100)}% за 8 недель
            </div>
          </QuestionBlock>
        </Reveal>

        <Reveal index={2}>
          <QuestionBlock
            question="Кто теряет больше всего?"
            answer={
              <>
                {ranking[0]!.title} — {perMonth(ranking[0]!.value)}. Нажмите на ресторан, чтобы открыть его неделю.
              </>
            }
            source={<VerifiedNote>открытые проблемы; «лучше / хуже» — по сравнению с прошлой неделей</VerifiedNote>}
            className="h-full"
          >
            <RankList items={ranking} />
          </QuestionBlock>
        </Reveal>
      </div>

      <Reveal index={3}>
        <QuestionBlock
          question="Где проблема не в одном ресторане, а в сети?"
          answer={
            systemic.length
              ? `${plural(systemic.length, ["процесс", "процесса", "процессов"])} проседает сразу в нескольких ресторанах — это повод для общего решения, а не задач каждому директору.`
              : "Системных проблем нет"
          }
        >
          <div className="grid gap-3 md:grid-cols-3">
            {systemic.map((p) => {
              const Icon = PROCESS_ICON[p.key];
              return (
                <Link
                  key={p.key}
                  to="/findings"
                  className="rounded-[14px] border border-line p-4 transition hover:border-ink-3"
                >
                  <div className="flex items-center gap-2 font-medium">
                    <span className={cx("grid h-8 w-8 place-items-center rounded-[9px] bg-loss-soft text-loss")}>
                      <Icon size={17} strokeWidth={1.75} />
                    </span>
                    {p.title}
                  </div>
                  <div className="mt-2 text-sm">
                    {p.losses ? <span className="num font-semibold text-loss">{perMonth(p.losses)}</span> : <span className="text-warn">пробел в данных</span>}
                  </div>
                  <div className="mt-1 text-xs text-ink-3">{p.hit.map((r) => r.name.replace("Ресторан ", "")).join(", ")}</div>
                </Link>
              );
            })}
          </div>
          {networkWide.length > 0 && (
            <div className="mt-5 border-t border-line pt-3">
              <div className="mb-1 px-3 text-sm font-medium">Общие для всей сети</div>
              {networkWide.map((f) => (
                <FindingRow key={f.id} f={f} showRestaurant />
              ))}
            </div>
          )}
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
