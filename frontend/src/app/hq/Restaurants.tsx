import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowDown, ArrowDownRight, ArrowLeft, ArrowUp, ArrowUpRight, Search } from "lucide-react";
import { useState } from "react";

import { Card, cx, PageTitle, Pill, Reveal } from "../../ds/primitives";
import { pct, plural, rub } from "../../lib/format";
import { FRESHNESS, KPIS, LOSSES_LAST_WEEK, RESTAURANTS } from "../../mock/data";
import { PROCESSES, processStatus, restaurantFindings } from "../../mock/selectors";
import { useTasks } from "../counts";
import { WeekView } from "../director/Week";

type SortKey = "losses" | "potential" | "foodCost" | "delta" | "late" | "tasksDone" | "name";

interface Row {
  code: string;
  name: string;
  city: string;
  losses: number;
  potential: number;
  foodCost: number;
  delta: number;
  late: number;
  tasksDone: number;
  tasksTotal: number;
  badProcesses: number;
  staleData: string | null;
}

function SortTh({
  k,
  children,
  right = true,
  sort,
  onSort,
}: {
  k: SortKey;
  children: React.ReactNode;
  right?: boolean;
  sort: { key: SortKey; desc: boolean };
  onSort: (next: (s: { key: SortKey; desc: boolean }) => { key: SortKey; desc: boolean }) => void;
}) {
  const active = sort.key === k;
  const Icon = sort.desc ? ArrowDown : ArrowUp;
  return (
    <th className={cx("px-4 py-2.5 font-medium", right && "text-right")}>
      <button
        type="button"
        onClick={() => onSort((s) => ({ key: k, desc: s.key === k ? !s.desc : k !== "name" }))}
        className={cx("inline-flex items-center gap-1 hover:text-ink", active ? "text-ink" : "text-ink-3")}
        aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
      >
        {children}
        {active && <Icon size={12} />}
      </button>
    </th>
  );
}

/** The general list of restaurants: search and sort by any column; built to stay usable at 100+ rows. */
export function RestaurantsPage() {
  const navigate = useNavigate();
  const tasks = useTasks();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "losses", desc: true });

  const rows: Row[] = RESTAURANTS.map((r) => {
    const { losses, potential } = restaurantFindings(r.code);
    const stale = FRESHNESS.find((f) => f.restaurantId === r.code && f.status !== "good");
    return {
      code: r.code,
      name: r.name,
      city: r.city,
      losses,
      potential,
      foodCost: KPIS[r.code]!.foodCostActual,
      delta: losses - (LOSSES_LAST_WEEK[r.code] ?? losses),
      late: tasks.filter((t) => t.restaurantId === r.code && t.status === "overdue").length,
      tasksDone: tasks.filter((t) => t.restaurantId === r.code && t.status === "done").length,
      tasksTotal: tasks.filter((t) => t.restaurantId === r.code).length,
      badProcesses: PROCESSES.filter((p) => processStatus(r.code, p.key).status !== "good").length,
      staleData: stale ? `${stale.dataset} по ${stale.lastDate}` : null,
    };
  });
  const q = query.trim().toLowerCase();
  const shown = rows
    .filter((r) => !q || r.name.toLowerCase().includes(q) || r.city.toLowerCase().includes(q))
    .sort((a, b) => {
      const dir = sort.desc ? -1 : 1;
      return sort.key === "name" ? dir * a.name.localeCompare(b.name) : dir * (a[sort.key] - b[sort.key]);
    });
  const maxLoss = Math.max(...rows.map((r) => r.losses), 1);
  const totalLoss = rows.reduce((acc, r) => acc + r.losses, 0);

  return (
    <div className="mx-auto max-w-[1180px]">
      <PageTitle
        title="Рестораны"
        subtitle={`${plural(rows.length, ["ресторан", "ресторана", "ресторанов"])} · теряют вместе ${rub(totalLoss)} в месяц. Нажмите на заголовок колонки, чтобы отсортировать.`}
      />
      <Reveal>
        <Card className="p-2">
          <div className="flex flex-wrap items-center justify-between gap-3 px-3 pt-3 pb-2">
            <label className="flex h-10 w-full max-w-sm items-center gap-2 rounded-[10px] border border-line-strong px-3 text-sm focus-within:border-brand">
              <Search size={15} className="text-ink-3" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти ресторан или город" aria-label="Найти ресторан" className="w-full outline-none" />
            </label>
            <span className="text-sm text-ink-3">Показано: {shown.length}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="text-left text-xs">
                <tr className="border-b border-line">
                  <SortTh sort={sort} onSort={setSort} k="name" right={false}>
                    Ресторан
                  </SortTh>
                  <SortTh sort={sort} onSort={setSort} k="losses">Теряем в месяц</SortTh>
                  <SortTh sort={sort} onSort={setSort} k="potential">Можно заработать</SortTh>
                  <SortTh sort={sort} onSort={setSort} k="delta">К прошлой неделе</SortTh>
                  <SortTh sort={sort} onSort={setSort} k="foodCost">Фудкост</SortTh>
                  <SortTh sort={sort} onSort={setSort} k="late">Просрочено задач</SortTh>
                  <SortTh sort={sort} onSort={setSort} k="tasksDone">
                    Задачи выполнены
                  </SortTh>
                  <th className="px-4 py-2.5 font-medium text-ink-3">Данные</th>
                </tr>
              </thead>
              <tbody className="num">
                {shown.map((r) => (
                  <tr
                    key={r.code}
                    onClick={() => void navigate({ to: "/restaurants/$code", params: { code: r.code } })}
                    className="cursor-pointer border-b border-line last:border-0 hover:bg-paper"
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-ink">{r.name}</div>
                      <div className="text-xs text-ink-3">
                        {r.city} · проблемы в {r.badProcesses} из 8 процессов
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="font-semibold text-loss">{rub(r.losses)}</div>
                      <div className="mt-1 ml-auto h-1 w-24 overflow-hidden rounded-full bg-ink/5">
                        <div className="h-full rounded-full bg-loss-icon" style={{ width: `${(r.losses / maxLoss) * 100}%` }} />
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-gain">{rub(r.potential)}</td>
                    <td className="px-4 py-3 text-right">
                      {r.delta === 0 ? (
                        <span className="text-ink-3">без изменений</span>
                      ) : (
                        <span className={cx("inline-flex items-center gap-0.5", r.delta < 0 ? "text-gain" : "text-loss")}>
                          {r.delta < 0 ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}
                          {r.delta < 0 ? "лучше" : "хуже"} на {rub(Math.abs(r.delta))}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">{pct(r.foodCost)}</td>
                    <td className={cx("px-4 py-3 text-right", r.late ? "font-semibold text-loss" : "text-ink-3")}>{r.late || "—"}</td>
                    <td className="px-4 py-3 text-right text-ink-2">{r.tasksTotal ? `${r.tasksDone} из ${r.tasksTotal}` : "—"}</td>
                    <td className="px-4 py-3">
                      {r.staleData ? <Pill tone="warn">{r.staleData}</Pill> : <Pill tone="gain">свежие</Pill>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </Reveal>
    </div>
  );
}

export function RestaurantPage() {
  const { code } = useParams({ from: "/app/restaurants/$code" });
  return (
    <div className="space-y-4">
      <Link to="/restaurants" className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> Все рестораны
      </Link>
      <WeekView code={code} readOnly />
    </div>
  );
}
