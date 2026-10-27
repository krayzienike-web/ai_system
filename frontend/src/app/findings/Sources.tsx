import { ChevronDown, FileText } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { useFindingSources } from "../../api/hooks";
import type { SourceGroup } from "../../api/types";
import { Card, cx, ErrorText, Skeleton } from "../../ds/primitives";
import { ddmm, kopecks, num, plural } from "../../lib/format";

type Cell = string | number | null | undefined;

/** A cell as loaded: the server gives the value and its type, the screen only formats it. */
function show(type: string, value: Cell, unit?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (type === "date") return ddmm(String(value));
  if (type === "money") return kopecks(Number(value));
  if (type === "qty") return `${num(Math.round(Number(value) * 1000) / 1000)}${unit ? ` ${unit}` : ""}`;
  return String(value);
}

function DocumentsTable({ group }: { group: SourceGroup }) {
  const numeric = (type: string) => type === "qty" || type === "money";
  return (
    <div className="overflow-x-auto">
      {group.same.length > 0 && <p className="mb-1 text-sm font-medium">{group.same.join(" · ")}</p>}
      <table className="w-full min-w-[560px] text-sm">
        <thead className="text-left text-ink-3">
          <tr>
            {group.columns.map((c) => (
              <th key={c.key} className={cx("py-2 pr-4 font-medium whitespace-nowrap", numeric(c.type) && "text-right")}>
                {c.label}
              </th>
            ))}
            <th className="py-2 font-medium">Файл</th>
          </tr>
        </thead>
        <tbody className="num">
          {group.rows.map((row, i) => (
            <tr key={i} className="border-t border-line align-top">
              {group.columns.map((c) => (
                <td key={c.key} className={cx("py-2 pr-4", (numeric(c.type) || c.key === "doc_no") && "whitespace-nowrap", numeric(c.type) && "text-right")}>
                  {show(c.type, row[c.key] as Cell, c.type === "qty" ? (row.unit as string | undefined) : undefined)}
                </td>
              ))}
              <td className="py-2 text-xs text-ink-3">
                <span className="inline-flex items-center gap-1 whitespace-nowrap">
                  <FileText size={12} aria-hidden />
                  {String(row.file ?? "—")}
                  {row.loaded_on ? ` · ${ddmm(String(row.loaded_on))}` : ""}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {group.total > group.rows.length && (
        <p className="mt-2 text-xs text-ink-3">
          Показаны первые {group.rows.length} из {group.total}. Остальное — в файлах на странице «Данные».
        </p>
      )}
    </div>
  );
}

/** «Документы»: the invoices, counts, write-offs, transfers and sales behind the finding, each with its file. */
export function SourceDocuments({ findingId }: { findingId: string }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState(0);
  const sources = useFindingSources(findingId, open);
  const groups = sources.data?.groups ?? [];
  const current = Math.min(tab, Math.max(groups.length - 1, 0));
  const group = groups[current];

  return (
    <Card className="overflow-hidden p-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="docs-body"
        className="flex w-full items-center justify-between px-6 py-4 text-left"
      >
        <span>
          <span className="block text-[13px] font-semibold tracking-[0.06em] text-ink-3 uppercase">Документы</span>
          <span className="font-medium">Накладные, инвентаризации, списания — строки из загруженных файлов</span>
        </span>
        <ChevronDown size={18} className={open ? "rotate-180 transition" : "transition"} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div id="docs-body" className="space-y-3 px-6 pb-5">
              {sources.isPending && <Skeleton className="h-40" />}
              <ErrorText error={sources.error} fallback="Не получилось загрузить документы" />
              {sources.data && <p className="text-sm text-ink-2">{sources.data.note}</p>}
              {groups.length > 1 && (
                <div
                  role="tablist"
                  aria-label="Виды документов"
                  className="flex flex-wrap gap-1"
                  onKeyDown={(e) => {
                    // Arrows move between the tabs (WAI-ARIA tabs pattern).
                    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
                    const next = (current + (e.key === "ArrowRight" ? 1 : groups.length - 1)) % groups.length;
                    setTab(next);
                    e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
                  }}
                >
                  {groups.map((g, i) => (
                    <button
                      key={g.kind}
                      id={`docs-tab-${g.kind}`}
                      type="button"
                      role="tab"
                      aria-selected={group === g}
                      aria-controls="docs-panel"
                      tabIndex={group === g ? 0 : -1}
                      onClick={() => setTab(i)}
                      className={cx(
                        "rounded-full px-3 py-1 text-sm",
                        group === g ? "bg-brand-soft font-medium text-brand-strong" : "text-ink-2 hover:bg-paper",
                      )}
                    >
                      {g.title} · {plural(g.total, ["строка", "строки", "строк"])}
                    </button>
                  ))}
                </div>
              )}
              {group && (
                <div id="docs-panel" role="tabpanel" aria-labelledby={groups.length > 1 ? `docs-tab-${group.kind}` : undefined}>
                  <DocumentsTable group={group} />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
