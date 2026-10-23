import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

import { DigestView } from "../components/DigestView";
import { Card, PageHeader, StatusChip } from "../components/ui";
import { pct, rubMonth } from "../lib/format";
import { FRESHNESS, KPIS, RESTAURANTS } from "../mock/data";
import { PROCESSES, processStatus, restaurantFindings } from "../mock/selectors";

export function RestaurantsPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Рестораны" meta="Нажмите на ресторан, чтобы открыть его сводку — как ее видит директор" />
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-normal">Ресторан</th>
              <th className="px-3 py-2 text-right font-normal">Теряем</th>
              <th className="px-3 py-2 text-right font-normal">Можем заработать</th>
              <th className="px-3 py-2 text-right font-normal">Фудкост факт / ТТК</th>
              <th className="px-3 py-2 text-right font-normal">Списания</th>
              <th className="px-3 py-2 font-normal">Процессы с проблемами</th>
              <th className="px-3 py-2 font-normal">Данные</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {RESTAURANTS.map((r) => {
              const f = restaurantFindings(r.code);
              const k = KPIS[r.code]!;
              const bad = PROCESSES.filter((p) => processStatus(r.code, p.key).status !== "good").length;
              const stale = FRESHNESS.some((x) => x.restaurantId === r.code && x.status !== "good");
              return (
                <tr
                  key={r.code}
                  className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                  onClick={() => navigate({ to: "/restaurants/$code", params: { code: r.code } })}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-900">{r.name}</div>
                    <div className="text-xs text-slate-500">
                      {r.code} · {r.city}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right text-red-700">{rubMonth(f.losses)}</td>
                  <td className="px-3 py-2 text-right text-emerald-700">{rubMonth(f.potential)}</td>
                  <td className="px-3 py-2 text-right">
                    {pct(k.foodCostActual)} / {pct(k.foodCostTheoretical)}
                  </td>
                  <td className="px-3 py-2 text-right">{pct(k.writeoffsPct)}</td>
                  <td className="px-3 py-2">{bad} из 8</td>
                  <td className="px-3 py-2">
                    <StatusChip status={stale ? "warning" : "good"} label={stale ? "есть отставание" : "свежие"} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export function RestaurantPage() {
  const { code } = useParams({ from: "/app/restaurants/$code" });
  return (
    <div>
      <Link to="/restaurants" className="mx-auto mb-4 flex max-w-6xl items-center gap-1 text-sm text-slate-600 hover:underline">
        <ArrowLeft size={14} /> Рестораны
      </Link>
      <DigestView code={code} isDirector={false} />
    </div>
  );
}
