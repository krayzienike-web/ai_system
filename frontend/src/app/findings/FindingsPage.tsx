import { useState } from "react";

import { Card, cx, EmptyState, PageTitle, Reveal } from "../../ds/primitives";
import { PROCESS_ICON } from "../../ds/viz";
import { perMonth, plural } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { FINDINGS, RESTAURANTS } from "../../mock/data";
import { PROCESSES } from "../../mock/selectors";
import type { ProcessKey } from "../../mock/types";
import { FindingRow } from "./parts";

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        "inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm transition-colors",
        active ? "border-ink bg-ink text-white" : "border-line-strong bg-surface text-ink-2 hover:border-ink-3",
      )}
    >
      {children}
    </button>
  );
}

export function FindingsPage() {
  const viewer = useViewer();
  const [kind, setKind] = useState<"all" | "problem" | "opportunity">("all");
  const [process, setProcess] = useState<ProcessKey | "all">("all");
  const [restaurant, setRestaurant] = useState<string>("all");
  if (!viewer) return null;

  const scope = FINDINGS.filter((f) => viewer.isHq || f.restaurantId === viewer.restaurantCode);
  const items = scope
    .filter(
      (f) =>
        (kind === "all" || f.kind === kind) &&
        (process === "all" || f.process === process) &&
        (restaurant === "all" || (f.restaurantId ?? "net") === restaurant),
    )
    .sort((a, b) => (b.effectRubMonth ?? -1) - (a.effectRubMonth ?? -1));
  const sum = items.reduce((acc, f) => acc + (f.effectRubMonth ?? 0), 0);
  const count = (k: typeof kind) => scope.filter((f) => k === "all" || f.kind === k).length;

  return (
    <div className="mx-auto max-w-[1040px]">
      <PageTitle
        title={viewer.isHq ? "Находки сети" : "Все находки ресторана"}
        subtitle={`${plural(items.length, ["находка", "находки", "находок"])} · в сумме ${perMonth(sum)}. Сначала самые дорогие.`}
      />
      <Reveal>
        <div className="mb-3 flex flex-wrap gap-2">
          <Chip active={kind === "all"} onClick={() => setKind("all")}>
            Все <span className="num opacity-60">{count("all")}</span>
          </Chip>
          <Chip active={kind === "problem"} onClick={() => setKind("problem")}>
            Где теряем <span className="num opacity-60">{count("problem")}</span>
          </Chip>
          <Chip active={kind === "opportunity"} onClick={() => setKind("opportunity")}>
            Где можно заработать <span className="num opacity-60">{count("opportunity")}</span>
          </Chip>
          {viewer.isHq && (
            <select
              value={restaurant}
              onChange={(e) => setRestaurant(e.target.value)}
              aria-label="Ресторан"
              className="h-9 rounded-full border border-line-strong bg-surface px-3.5 text-sm text-ink-2"
            >
              <option value="all">Все рестораны</option>
              {RESTAURANTS.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
              <option value="net">Вся сеть (общие)</option>
            </select>
          )}
        </div>
        <div className="mb-5 flex flex-wrap gap-1.5">
          <Chip active={process === "all"} onClick={() => setProcess("all")}>
            Все процессы
          </Chip>
          {PROCESSES.filter((p) => scope.some((f) => f.process === p.key)).map((p) => {
            const Icon = PROCESS_ICON[p.key];
            return (
              <Chip key={p.key} active={process === p.key} onClick={() => setProcess(p.key)}>
                <Icon size={14} strokeWidth={1.75} /> {p.title}
              </Chip>
            );
          })}
        </div>
      </Reveal>
      <Reveal index={1}>
        {items.length ? (
          <Card className="p-2">
            {items.map((f) => (
              <FindingRow key={f.id} f={f} showRestaurant={viewer.isHq} />
            ))}
          </Card>
        ) : (
          <EmptyState title="Таких находок нет">Попробуйте другой процесс или вид.</EmptyState>
        )}
      </Reveal>
    </div>
  );
}
