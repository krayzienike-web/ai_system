import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { EffectValue, STATUS_LABELS, useFindingStatus } from "../components/FindingCard";
import { Card, ConfidenceBadge, PageHeader, Pill } from "../components/ui";
import { rubMonth } from "../lib/format";
import { FINDINGS, RESTAURANTS } from "../mock/data";
import { PROCESSES, processTitle } from "../mock/selectors";
import type { Finding } from "../mock/types";

function Row({ finding }: { finding: Finding }) {
  const navigate = useNavigate();
  const status = useFindingStatus(finding);
  return (
    <tr
      className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
      onClick={() => navigate({ to: "/insights/$findingId", params: { findingId: finding.id } })}
    >
      <td className="px-3 py-2">
        <div className="font-medium text-slate-900">{finding.title}</div>
        <div className="text-xs text-slate-500">
          {finding.metric.label}: {finding.metric.value} · {finding.metric.benchmark}
        </div>
      </td>
      <td className="px-3 py-2 text-sm">{RESTAURANTS.find((r) => r.code === finding.restaurantId)?.name ?? "Вся сеть"}</td>
      <td className="px-3 py-2 text-sm">{processTitle(finding.process)}</td>
      <td className="px-3 py-2">
        <Pill tone={finding.kind === "problem" ? "loss" : "gain"}>{finding.kind === "problem" ? "Проблема" : "Возможность"}</Pill>
      </td>
      <td className="px-3 py-2 text-right">
        <EffectValue finding={finding} className="text-sm" />
      </td>
      <td className="px-3 py-2">
        <ConfidenceBadge confidence={finding.confidence} />
      </td>
      <td className="px-3 py-2 text-sm text-slate-600">{STATUS_LABELS[status]}</td>
    </tr>
  );
}

const select = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm";

export function InsightsPage() {
  const [kind, setKind] = useState("all");
  const [restaurant, setRestaurant] = useState("all");
  const [process, setProcess] = useState("all");

  const items = FINDINGS.filter(
    (f) =>
      (kind === "all" || f.kind === kind) &&
      (restaurant === "all" || (f.restaurantId ?? "net") === restaurant) &&
      (process === "all" || f.process === process),
  ).sort((a, b) => (b.effectRubMonth ?? -1) - (a.effectRubMonth ?? -1));
  const total = items.reduce((acc, f) => acc + (f.effectRubMonth ?? 0), 0);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Инсайты" meta={`${items.length} находок · сумма ${rubMonth(total)}`} />
      <div className="mb-4 flex flex-wrap gap-2">
        <select className={select} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Вид">
          <option value="all">Проблемы и возможности</option>
          <option value="problem">Только проблемы</option>
          <option value="opportunity">Только возможности</option>
        </select>
        <select className={select} value={restaurant} onChange={(e) => setRestaurant(e.target.value)} aria-label="Ресторан">
          <option value="all">Все рестораны</option>
          {RESTAURANTS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.name}
            </option>
          ))}
          <option value="net">Вся сеть</option>
        </select>
        <select className={select} value={process} onChange={(e) => setProcess(e.target.value)} aria-label="Процесс">
          <option value="all">Все процессы</option>
          {PROCESSES.map((p) => (
            <option key={p.key} value={p.key}>
              {p.title}
            </option>
          ))}
        </select>
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[900px]">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-normal">Находка</th>
              <th className="px-3 py-2 font-normal">Ресторан</th>
              <th className="px-3 py-2 font-normal">Процесс</th>
              <th className="px-3 py-2 font-normal">Вид</th>
              <th className="px-3 py-2 text-right font-normal">Эффект</th>
              <th className="px-3 py-2 font-normal">Уверенность</th>
              <th className="px-3 py-2 font-normal">Статус</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <Row key={f.id} finding={f} />
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
