import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

import { VerifiedNote } from "../../ds/ai";
import { PageTitle, Pill, QuestionBlock, Reveal } from "../../ds/primitives";
import { RankList } from "../../ds/viz";
import { pct, perMonth, rub } from "../../lib/format";
import { FRESHNESS, KPIS, LOSSES_LAST_WEEK, RESTAURANTS } from "../../mock/data";
import { networkKpis, PROCESSES, processStatus, restaurantFindings } from "../../mock/selectors";
import { WeekView } from "../director/Week";

export function RestaurantsPage() {
  const navigate = useNavigate();
  const open = (code: string) => () => void navigate({ to: "/restaurants/$code", params: { code } });
  const byLoss = RESTAURANTS.map((r) => {
    const { losses, potential } = restaurantFindings(r.code);
    return {
      id: r.code,
      title: r.name,
      value: losses,
      valueLabel: rub(losses),
      delta: losses - (LOSSES_LAST_WEEK[r.code] ?? losses),
      sub: `Можно заработать ещё ${perMonth(potential)} · ${PROCESSES.filter((p) => processStatus(r.code, p.key).status !== "good").length} из 8 процессов с проблемами`,
      onClick: open(r.code),
    };
  }).sort((a, b) => b.value - a.value);
  const byFoodCost = RESTAURANTS.map((r) => ({
    id: r.code,
    title: r.name,
    value: KPIS[r.code]!.foodCostActual,
    valueLabel: pct(KPIS[r.code]!.foodCostActual),
    sub: `по техкартам ${pct(KPIS[r.code]!.foodCostTheoretical)} · разница ${(KPIS[r.code]!.foodCostActual - KPIS[r.code]!.foodCostTheoretical).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} пункта`,
    onClick: open(r.code),
  })).sort((a, b) => b.value - a.value);

  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <PageTitle title="Рестораны" subtitle="Откройте ресторан, чтобы увидеть его неделю так, как ее видит директор" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Reveal>
          <QuestionBlock question="Кто теряет больше?" answer={`${byLoss[0]!.title} — ${perMonth(byLoss[0]!.value)}`} className="h-full">
            <RankList items={byLoss} />
          </QuestionBlock>
        </Reveal>
        <Reveal index={1}>
          <QuestionBlock
            question="У кого выше фудкост?"
            answer={`Среднее по сети — ${pct(networkKpis().foodCostActual)}; выше всех — ${byFoodCost[0]!.title}`}
            source={<VerifiedNote>период между инвентаризациями 03.08–01.10</VerifiedNote>}
            className="h-full"
          >
            <RankList items={byFoodCost} />
          </QuestionBlock>
        </Reveal>
      </div>
      <Reveal index={2}>
        <QuestionBlock question="Свежие ли данные?" answer="Чтобы выводы были точными, данные должны приходить каждую неделю.">
          <div className="grid gap-3 sm:grid-cols-3">
            {RESTAURANTS.map((r) => {
              const stale = FRESHNESS.filter((f) => f.restaurantId === r.code && f.status !== "good");
              return (
                <Link key={r.code} to="/data" className="rounded-[14px] border border-line p-4 hover:border-ink-3">
                  <div className="font-medium">{r.name}</div>
                  <div className="mt-2">
                    {stale.length ? (
                      <Pill tone="warn">
                        {stale[0]!.dataset} — по {stale[0]!.lastDate}
                      </Pill>
                    ) : (
                      <Pill tone="gain">Все данные свежие</Pill>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        </QuestionBlock>
      </Reveal>
    </div>
  );
}

export function RestaurantPage() {
  const { code } = useParams({ from: "/app/restaurants/$code" });
  return (
    <div className="space-y-4">
      <Link to="/restaurants" className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> Рестораны
      </Link>
      <WeekView code={code} readOnly />
    </div>
  );
}
