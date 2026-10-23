import { Link } from "@tanstack/react-router";
import { CalendarClock, MessageCircle, Sparkles, TrendingUp } from "lucide-react";

import { pct, plural, rub, rubMonth } from "../lib/format";
import { DIGEST_TEXT, IMPROVEMENTS, KPIS, PERIOD, STOCK_RISKS } from "../mock/data";
import { networkKpis, restaurantByCode, restaurantFindings } from "../mock/selectors";
import { usePrototype } from "../state/prototype";
import { FindingCard } from "./FindingCard";
import { ProcessMap } from "./ProcessMap";
import { Button, Card, EmptyState, PageHeader, SectionTitle, StatTile, StatusIcon } from "./ui";

const diff = (own: number, avg: number) => {
  const d = own - avg;
  return `${d > 0 ? "+" : ""}${d.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} п.п. к среднему по сети`;
};

/** Weekly digest of one restaurant. Directors see it as their home; HQ opens it from the restaurant list. */
export function DigestView({ code, isDirector }: { code: string; isDirector: boolean }) {
  const { openChat } = usePrototype();
  const restaurant = restaurantByCode(code);
  if (!restaurant) return <EmptyState title="Ресторан не найден" />;

  const { problems, opportunities, losses, potential } = restaurantFindings(code);
  const kpi = KPIS[code]!;
  const avg = networkKpis();
  const risks = STOCK_RISKS.filter((r) => r.restaurantId === code);
  const improvements = IMPROVEMENTS.filter((i) => i.restaurantId === code);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title={restaurant.name}
        meta={
          <>
            Неделя {PERIOD.week} · данные по {PERIOD.dataUntil} · последняя инвентаризация {PERIOD.lastInventory}
          </>
        }
        actions={
          <Button onClick={() => openChat({ title: `Сводка: ${restaurant.name}` })}>
            <MessageCircle size={14} /> Спросить ИИ о неделе
          </Button>
        }
      />

      <Card className="mb-6 border-blue-100 bg-blue-50/40 p-4">
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-blue-800">
          <Sparkles size={14} /> Главное за неделю
        </div>
        <p className="text-slate-800">{DIGEST_TEXT[code]}</p>
      </Card>

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="На столе" value={rubMonth(losses + potential)} sub="потери + потенциал" />
        <StatTile label="Теряем" value={rubMonth(losses)} tone="loss" sub={plural(problems.length, ["проблема", "проблемы", "проблем"])} />
        <StatTile label="Можем заработать" value={rubMonth(potential)} tone="gain" sub={plural(opportunities.length, ["возможность", "возможности", "возможностей"])} />
        <StatTile
          label="Фудкост факт"
          value={pct(kpi.foodCostActual)}
          sub={
            <>
              по ТТК {pct(kpi.foodCostTheoretical)} · {diff(kpi.foodCostActual, avg.foodCostActual)}
            </>
          }
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section>
            <SectionTitle aside="по данным недели и последней инвентаризации">Процессы ресторана</SectionTitle>
            <ProcessMap restaurantId={code} />
          </section>

          <section>
            <SectionTitle aside={`−${rubMonth(losses)}`}>Проблемы: где теряем</SectionTitle>
            <div className="space-y-3">
              {problems.length ? (
                problems.map((f) => <FindingCard key={f.id} finding={f} isDirector={isDirector} />)
              ) : (
                <EmptyState title="Проблем выше нормы не найдено">Посмотрите возможности ниже.</EmptyState>
              )}
            </div>
          </section>

          <section>
            <SectionTitle aside={`+${rubMonth(potential)}`}>Возможности: что улучшить</SectionTitle>
            <div className="space-y-3">
              {opportunities.map((f) => (
                <FindingCard key={f.id} finding={f} isDirector={isDirector} />
              ))}
            </div>
          </section>
        </div>

        <aside className="space-y-6">
          <Card className="p-4">
            <SectionTitle>Риски дефицита</SectionTitle>
            {risks.length ? (
              <ul className="space-y-3">
                {risks.map((r) => (
                  <li key={r.product} className="flex gap-2 text-sm">
                    <StatusIcon status={r.daysLeft < r.nextDeliveryInDays ? "critical" : "warning"} />
                    <div>
                      <div className="font-medium text-slate-800">{r.product}</div>
                      <div className="text-slate-500">
                        хватит на {r.daysLeft} дн., поставка через {r.nextDeliveryInDays} дн. · {r.supplier}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-slate-500">Рисков на ближайшие дни нет.</div>
            )}
          </Card>

          <Card className="p-4">
            <SectionTitle>Что улучшилось</SectionTitle>
            <ul className="space-y-2 text-sm text-slate-700">
              {improvements.map((i) => (
                <li key={i.text} className="flex gap-2">
                  <TrendingUp size={16} className="shrink-0 text-emerald-700" aria-hidden />
                  {i.text}
                </li>
              ))}
            </ul>
          </Card>

          <Card className="p-4">
            <SectionTitle>Сравнение со средним по сети</SectionTitle>
            <dl className="space-y-2 text-sm">
              {[
                ["Фудкост факт", pct(kpi.foodCostActual), pct(avg.foodCostActual)],
                ["Фудкост по ТТК", pct(kpi.foodCostTheoretical), pct(avg.foodCostTheoretical)],
                ["Списания, % выручки", pct(kpi.writeoffsPct), pct(avg.writeoffsPct)],
                ["Переплаты в закупке", rubMonth(kpi.overpayRubMonth), rubMonth(Math.round(avg.overpayRubMonth))],
              ].map(([label, own, network]) => (
                <div key={label} className="grid grid-cols-[1fr_auto_auto] gap-3 tabular-nums">
                  <dt className="text-slate-600">{label}</dt>
                  <dd className="text-right font-medium text-slate-900">{own}</dd>
                  <dd className="text-right text-slate-500">{network}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-2 text-xs text-slate-500">Справа — среднее по сети, взвешенное по выручке.</div>
          </Card>

          <Card className="p-4 text-sm text-slate-600">
            <div className="mb-1 flex items-center gap-1.5 font-medium text-slate-800">
              <CalendarClock size={16} /> Следующая инвентаризация — {PERIOD.nextInventory}
            </div>
            Потери по ТТК пересчитаются после нее. Выручка ресторана в месяц — {rub(restaurant.revenueMonth)}.
            {isDirector && (
              <div className="mt-2">
                <Link to="/tasks" className="underline">
                  Мои задачи
                </Link>
              </div>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}
