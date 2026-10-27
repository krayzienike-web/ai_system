import { useNavigate } from "@tanstack/react-router";

import type { NetworkOverview } from "../../api/types";
import { cx } from "../../ds/primitives";
import { PROCESS_ICON } from "../../ds/viz";
import { money, rub } from "../../lib/format";

const TONE: Record<string, string> = {
  critical: "bg-loss-soft text-loss font-semibold hover:ring-loss-icon/60",
  warning: "bg-warn-soft text-warn hover:ring-warn/60",
  good: "text-ink-3",
};

/** Restaurants × processes (docs/10, 4.3): losses in ₽ a month; a cell opens that restaurant's findings there. */
export function ProcessMatrix({ n }: { n: NetworkOverview }) {
  const navigate = useNavigate();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] border-separate border-spacing-1 text-sm">
        <thead>
          <tr className="text-xs text-ink-3">
            <th className="sticky left-0 bg-surface py-1 pr-2 text-left font-medium">Ресторан</th>
            {n.processes.map((p) => {
              const Icon = PROCESS_ICON[p.process as keyof typeof PROCESS_ICON];
              return (
                <th key={p.process} className="px-1 py-1 text-center align-bottom font-medium" title={p.title}>
                  {Icon && <Icon size={15} className="mx-auto mb-1" aria-hidden />}
                  <span className="block leading-tight">{p.short}</span>
                </th>
              );
            })}
            <th className="px-1 py-1 text-right font-medium">Итого</th>
          </tr>
        </thead>
        <tbody className="num">
          {n.matrix.map((row) => (
            <tr key={row.code}>
              <th scope="row" className="sticky left-0 bg-surface py-1 pr-2 text-left font-medium whitespace-nowrap">
                {row.short_name}
              </th>
              {row.cells.map((c) => {
                const losses = money(c.losses) ?? 0;
                const title = n.processes.find((p) => p.process === c.process)?.title ?? c.process;
                if (c.status === "good")
                  return (
                    <td key={c.process} className="rounded-[8px] px-2 py-2 text-center text-ink-3" aria-label={`${title}: в норме`}>
                      ·
                    </td>
                  );
                return (
                  <td key={c.process} className="p-0">
                    <button
                      type="button"
                      onClick={() => void navigate({ to: "/findings", search: { restaurant: row.id, process: c.process } })}
                      className={cx("w-full rounded-[8px] px-2 py-2 text-center ring-1 ring-transparent transition", TONE[c.status])}
                      aria-label={`${row.name}, ${title}: ${losses ? rub(losses) : `${c.count} без оценки в рублях`}`}
                    >
                      {losses ? rub(losses).replace(" ₽", "") : "без ₽"}
                    </button>
                  </td>
                );
              })}
              <td className="px-1 py-2 text-right font-semibold whitespace-nowrap">{money(row.total) ? rub(money(row.total) ?? 0) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
