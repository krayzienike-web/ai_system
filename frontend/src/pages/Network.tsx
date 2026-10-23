import { Link } from "@tanstack/react-router";
import { FlaskConical, ListTodo } from "lucide-react";

import { FindingCard } from "../components/FindingCard";
import { Card, PageHeader, SectionTitle, StatTile, StatusIcon } from "../components/ui";
import { pct, rub, rubMonth } from "../lib/format";
import { EXPERIMENTS, FINDINGS, FRESHNESS, KPIS, PERIOD, RESTAURANTS, TASKS } from "../mock/data";
import { networkKpis, networkTotals, PROCESSES, processStatus, restaurantFindings } from "../mock/selectors";

// Sequential blue ramp (reference palette, light): magnitude of losses per cell.
const RAMP = [
  { min: 30_000, bg: "#3987e5" },
  { min: 20_000, bg: "#6da7ec" },
  { min: 10_000, bg: "#9ec5f4" },
  { min: 1, bg: "#cde2fb" },
];
const cellBg = (value: number) => RAMP.find((s) => value >= s.min)?.bg;

export function NetworkPage() {
  const totals = networkTotals();
  const avg = networkKpis();
  const top = FINDINGS.filter((f) => f.status !== "resolved" && f.effectRubMonth !== null)
    .sort((a, b) => (b.effectRubMonth ?? 0) - (a.effectRubMonth ?? 0))
    .slice(0, 4);
  const networkWide = FINDINGS.filter((f) => f.restaurantId === null);
  const proposed = EXPERIMENTS.filter((e) => e.status === "proposed");
  const running = EXPERIMENTS.filter((e) => e.status === "running");
  const overdue = TASKS.filter((t) => t.status === "overdue");
  const stale = FRESHNESS.filter((f) => f.status !== "good");

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Обзор сети" meta={`${RESTAURANTS.length} ресторана · неделя ${PERIOD.week} · данные по ${PERIOD.dataUntil}`} />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="На столе" value={rubMonth(totals.losses + totals.potential)} sub={`≈ ${rub((totals.losses + totals.potential) * 12)} в год`} />
        <StatTile label="Теряем" value={rubMonth(totals.losses)} tone="loss" />
        <StatTile label="Можем заработать" value={rubMonth(totals.potential)} tone="gain" />
        <StatTile label="Подтверждено экспериментами" value={rubMonth(totals.confirmed)} sub="эффект, проверенный замером" />
      </div>

      <section className="mb-6">
        <SectionTitle aside="потери ₽/мес по открытым проблемам">Рестораны × процессы</SectionTitle>
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2 font-normal">Ресторан</th>
                {PROCESSES.map((p) => (
                  <th key={p.key} className="px-2 py-2 text-center font-normal">
                    {p.title}
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-normal">Итого</th>
                <th className="px-3 py-2 text-right font-normal">Фудкост</th>
              </tr>
            </thead>
            <tbody>
              {RESTAURANTS.map((r) => (
                <tr key={r.code} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    <Link to="/restaurants/$code" params={{ code: r.code }} className="font-medium text-slate-900 hover:underline">
                      {r.name}
                    </Link>
                  </td>
                  {PROCESSES.map((p) => {
                    const { status, losses } = processStatus(r.code, p.key);
                    return (
                      <td key={p.key} className="px-1 py-1">
                        <div
                          className="flex h-9 items-center justify-center gap-1 rounded tabular-nums text-slate-900"
                          style={{ background: cellBg(losses) }}
                          title={`${r.name} · ${p.title}`}
                        >
                          {status === "good" ? <StatusIcon status="good" size={14} /> : losses ? (losses / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 }) : <StatusIcon status={status} size={14} />}
                        </div>
                      </td>
                    );
                  })}
                  <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums">{rubMonth(restaurantFindings(r.code).losses)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{pct(KPIS[r.code]!.foodCostActual)}</td>
                </tr>
              ))}
              <tr className="border-t border-slate-200 text-slate-500">
                <td className="px-3 py-2" colSpan={PROCESSES.length + 2}>
                  Среднее по сети (взвешенное по выручке)
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{pct(avg.foodCostActual)}</td>
              </tr>
            </tbody>
          </table>
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
            <span>Значения в тыс ₽/мес.</span>
            {[...RAMP].reverse().map((s, i) => (
              <span key={s.bg} className="inline-flex items-center gap-1">
                <span className="inline-block h-3 w-5 rounded-sm" style={{ background: s.bg }} />
                {["до 10", "10–20", "20–30", "от 30"][i]}
              </span>
            ))}
            <span className="inline-flex items-center gap-1">
              <StatusIcon status="good" size={12} /> норма
            </span>
            <span className="inline-flex items-center gap-1">
              <StatusIcon status="warning" size={12} /> пробел без оценки в ₽
            </span>
          </div>
        </Card>
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="space-y-3 lg:col-span-2">
          <SectionTitle aside={<Link to="/insights" className="underline">Все инсайты</Link>}>Главное по сети</SectionTitle>
          {networkWide.map((f) => (
            <FindingCard key={f.id} finding={f} showRestaurant />
          ))}
          {top.map((f) => (
            <FindingCard key={f.id} finding={f} showRestaurant />
          ))}
        </section>
        <aside className="space-y-4">
          <Card className="p-4">
            <SectionTitle>
              <span className="inline-flex items-center gap-1.5">
                <FlaskConical size={16} /> Эксперименты
              </span>
            </SectionTitle>
            <ul className="space-y-2 text-sm">
              {proposed.map((e) => (
                <li key={e.id}>
                  <Link to="/experiments/$experimentId" params={{ experimentId: e.id }} className="font-medium underline">
                    Ждет утверждения: {e.title}
                  </Link>
                  <div className="text-slate-500">ожидаемый эффект {rubMonth(e.expectedRubMonth)}</div>
                </li>
              ))}
              {running.map((e) => (
                <li key={e.id}>
                  <Link to="/experiments/$experimentId" params={{ experimentId: e.id }} className="underline">
                    Идет: {e.title}
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-4">
            <SectionTitle>
              <span className="inline-flex items-center gap-1.5">
                <ListTodo size={16} /> Задачи
              </span>
            </SectionTitle>
            {overdue.map((t) => (
              <div key={t.id} className="flex gap-2 text-sm">
                <StatusIcon status="critical" />
                <div>
                  Просрочена: {t.title}
                  <div className="text-slate-500">
                    {RESTAURANTS.find((r) => r.code === t.restaurantId)?.name} · срок {t.due}
                  </div>
                </div>
              </div>
            ))}
            <Link to="/tasks" className="mt-2 inline-block text-sm underline">
              Все задачи
            </Link>
          </Card>
          <Card className="p-4">
            <SectionTitle>Данные</SectionTitle>
            {stale.map((f) => (
              <div key={f.restaurantId + f.source} className="flex gap-2 text-sm">
                <StatusIcon status={f.status} />
                <div>
                  {RESTAURANTS.find((r) => r.code === f.restaurantId)?.name}: {f.dataset.toLowerCase()} по {f.lastDate}
                  <div className="text-slate-500">{f.note}</div>
                </div>
              </div>
            ))}
            <Link to="/data" className="mt-2 inline-block text-sm underline">
              Свежесть данных
            </Link>
          </Card>
        </aside>
      </div>
    </div>
  );
}
