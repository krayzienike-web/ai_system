import { rubMonth } from "../lib/format";
import { PROCESSES, processStatus } from "../mock/selectors";
import { StatusChip, StatusIcon } from "./ui";

export function ProcessMap({ restaurantId }: { restaurantId: string }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {PROCESSES.map((p) => {
        const { status, losses } = processStatus(restaurantId, p.key);
        return (
          <div key={p.key} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
              <StatusIcon status={status} />
              {p.title}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {status === "good" ? <StatusChip status="good" label="Норма" /> : losses > 0 ? `−${rubMonth(losses)}` : "есть пробел в данных"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
