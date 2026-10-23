import { Link } from "@tanstack/react-router";
import { FlaskConical, ListTodo } from "lucide-react";

import { FindingCard } from "../components/FindingCard";
import { Card, PageHeader, SectionTitle, StatTile, StatusIcon } from "../components/ui";
import { plural, rub, rubMonth } from "../lib/format";
import { EXPERIMENTS, FINDINGS, FRESHNESS, PERIOD, RESTAURANTS, TASKS } from "../mock/data";
import { networkTotals, PROCESSES, processStatus } from "../mock/selectors";

interface LossPart {
  label: string;
  losses: number;
}

interface LossRow {
  key: string;
  title: string;
  code?: string;
  total: number;
  parts: LossPart[]; // processes (or restaurants) with open problems, largest first
  okNote: string;
}

/** One list = one question ("where are we losing money?"), answered row by row in rubles. */
function LossList({ title, rows }: { title: string; rows: LossRow[] }) {
  const max = Math.max(...rows.map((r) => r.total), 1);
  return (
    <Card className="p-4">
      <div className="mb-1 text-sm font-medium text-slate-500">{title}</div>
      <ul>
        {rows.map((row) => (
          <li key={row.key} className="border-t border-slate-100 py-3 first:border-t-0">
            <div className="flex items-baseline justify-between gap-3">
              {row.code ? (
                <Link to="/restaurants/$code" params={{ code: row.code }} className="font-medium text-slate-900 hover:underline">
                  {row.title}
                </Link>
              ) : (
                <span className="font-medium text-slate-900">{row.title}</span>
              )}
              {row.total ? (
                <span className="whitespace-nowrap font-semibold tabular-nums text-red-700">−{rubMonth(row.total)}</span>
              ) : (
                <span className="whitespace-nowrap text-sm text-slate-500">без оценки в ₽</span>
              )}
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-slate-100" aria-hidden>
              <div className="h-full rounded-full bg-red-600" style={{ width: `${(row.total / max) * 100}%` }} />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {row.parts.map((part) =>
                part.losses ? (
                  <span key={part.label} className="rounded-md bg-red-50 px-2 py-0.5 text-xs text-red-900">
                    {part.label} <span className="font-medium tabular-nums">{rub(part.losses)}</span>
                  </span>
                ) : (
                  <span key={part.label} className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-0.5 text-xs text-amber-900">
                    <StatusIcon status="warning" size={12} /> {part.label}: пробел в данных
                  </span>
                ),
              )}
            </div>
            <div className="mt-1 text-xs text-slate-500">{row.okNote}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function lossesByRestaurant(): LossRow[] {
  return RESTAURANTS.map((r) => {
    const parts = PROCESSES.map((p) => ({ label: p.title, ...processStatus(r.code, p.key) }))
      .filter((p) => p.status !== "good")
      .sort((a, b) => b.losses - a.losses);
    const ok = PROCESSES.length - parts.length;
    return {
      key: r.code,
      code: r.code,
      title: r.name,
      total: parts.reduce((acc, p) => acc + p.losses, 0),
      parts,
      okNote: `В норме: ${plural(ok, ["процесс", "процесса", "процессов"])} из ${PROCESSES.length}`,
    };
  }).sort((a, b) => b.total - a.total);
}

function lossesByProcess(): LossRow[] {
  return PROCESSES.map((p) => {
    const parts = RESTAURANTS.map((r) => ({ label: r.name.replace("Ресторан ", ""), ...processStatus(r.code, p.key) }))
      .filter((x) => x.status !== "good")
      .sort((a, b) => b.losses - a.losses);
    const ok = RESTAURANTS.length - parts.length;
    return {
      key: p.key,
      title: p.title,
      total: parts.reduce((acc, x) => acc + x.losses, 0),
      parts,
      okNote: ok ? `В норме: ${plural(ok, ["ресторан", "ресторана", "ресторанов"])}` : "Проблема во всех ресторанах",
    };
  })
    .filter((row) => row.parts.length > 0)
    .sort((a, b) => b.total - a.total);
}

export function NetworkPage() {
  const totals = networkTotals();
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
        <SectionTitle aside="открытые проблемы, ₽ в месяц">Где сеть теряет деньги</SectionTitle>
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <LossList title="По ресторанам" rows={lossesByRestaurant()} />
          <LossList title="По процессам" rows={lossesByProcess()} />
        </div>
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
