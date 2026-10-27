import { Loader2, RefreshCw } from "lucide-react";

import { useLatestRun } from "../../api/hooks";
import { cx } from "../../ds/primitives";
import { ddmm } from "../../lib/format";

const time = (iso: string) => {
  const d = new Date(iso);
  return `${ddmm(iso.slice(0, 10))} в ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

/** «Находки пересчитаны 27.10 в 12:30 после загрузки файла» — or that a recalculation is going on now. */
export function RecalcNote({ className }: { className?: string }) {
  const run = useLatestRun().data;
  if (!run) return null;
  const busy = run.status === "queued" || run.status === "running";
  return (
    <p className={cx("inline-flex items-center gap-1.5 text-sm", run.status === "failed" ? "text-loss" : "text-ink-3", className)} aria-live="polite">
      {busy ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <RefreshCw size={14} aria-hidden />}
      {busy
        ? "Находки пересчитываются по новым данным…"
        : run.status === "failed"
          ? "Пересчет после загрузки не удался — нажмите «Пересчитать находки» или напишите в поддержку"
          : `Находки пересчитаны ${time(run.finished_at ?? run.requested_at)}${run.trigger === "upload" ? " после загрузки данных" : ""}`}
    </p>
  );
}
