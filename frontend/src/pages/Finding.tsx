import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, FlaskConical, MessageCircle, Sparkles } from "lucide-react";

import { DirectorActions, EffectValue, STATUS_LABELS } from "../components/FindingCard";
import { TrendChart } from "../components/TrendChart";
import { Button, buttonClass, Card, ConfidenceBadge, EmptyState, Pill, SectionTitle } from "../components/ui";
import { num, rub } from "../lib/format";
import { canSeeRestaurant, useViewer } from "../lib/useViewer";
import { EXPERIMENTS } from "../mock/data";
import { findingById, processTitle, restaurantByCode } from "../mock/selectors";
import { usePrototype } from "../state/prototype";

export function FindingPage() {
  const { findingId } = useParams({ from: "/app/insights/$findingId" });
  const viewer = useViewer();
  const { openChat, findingStatus } = usePrototype();
  const finding = findingById(findingId);

  if (!viewer) return null;
  // Same rule as the API: a director never sees another restaurant's findings.
  if (!finding || !canSeeRestaurant(viewer, finding.restaurantId)) {
    return <EmptyState title="Находка не найдена">Возможно, она относится к другому ресторану.</EmptyState>;
  }

  const status = findingStatus[finding.id] ?? finding.status;
  const restaurant = finding.restaurantId ? restaurantByCode(finding.restaurantId) : null;
  const experiment = EXPERIMENTS.find((e) => e.findingId === finding.id);
  const back = viewer.isHq ? { to: "/insights" as const, label: "Инсайты" } : { to: "/" as const, label: "Сводка недели" };

  return (
    <div className="mx-auto max-w-5xl">
      <Link to={back.to} className="mb-4 inline-flex items-center gap-1 text-sm text-slate-600 hover:underline">
        <ArrowLeft size={14} /> {back.label}
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Pill tone={finding.kind === "problem" ? "loss" : "gain"}>{finding.kind === "problem" ? "Проблема" : "Возможность"}</Pill>
            <Pill>{processTitle(finding.process)}</Pill>
            <Pill tone="info">{STATUS_LABELS[status]}</Pill>
          </div>
          <h1 className="text-2xl font-semibold text-slate-900">{finding.title}</h1>
          <div className="mt-1 text-sm text-slate-500">{restaurant ? restaurant.name : "Вся сеть"}</div>
        </div>
        <div className="text-right">
          <EffectValue finding={finding} className="text-2xl" />
          {finding.effectRubMonth !== null && <div className="text-xs text-slate-500">≈ {rub(finding.effectRubMonth * 12)} в год</div>}
          {finding.effectNote && <div className="text-xs text-slate-500">{finding.effectNote}</div>}
        </div>
      </div>

      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {viewer.isHq ? (
            <div className="flex flex-wrap gap-2">
              {experiment ? (
                <Link to="/experiments/$experimentId" params={{ experimentId: experiment.id }} className={buttonClass()}>
                  <FlaskConical size={14} /> Эксперимент: {experiment.title}
                </Link>
              ) : (
                <Link to="/experiments" search={{ draft: finding.id }} className={buttonClass("primary")}>
                  <FlaskConical size={14} /> Предложить эксперимент
                </Link>
              )}
              <Button variant="ghost" onClick={() => openChat({ title: finding.title, findingId: finding.id })}>
                <MessageCircle size={14} /> Обсудить с ИИ
              </Button>
            </div>
          ) : (
            <DirectorActions finding={finding} />
          )}
          <ConfidenceBadge confidence={finding.confidence} note={finding.confidenceNote} />
        </div>
        <div className="mt-2 text-xs text-slate-500">Основание уверенности: {finding.confidenceNote}</div>
      </Card>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <Card className="p-4">
          <div className="text-sm text-slate-500">{finding.metric.label}</div>
          <div className="mt-1 text-xl font-semibold tabular-nums">{finding.metric.value}</div>
        </Card>
        <Card className="p-4">
          <div className="text-sm text-slate-500">Сравнение</div>
          <div className="mt-1 font-medium">{finding.metric.benchmark}</div>
        </Card>
        <Card className="p-4">
          <div className="text-sm text-slate-500">Норма</div>
          <div className="mt-1 font-medium">{finding.metric.norm?.replace(/^норма /, "") ?? "—"}</div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-4">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-blue-800">
            <Sparkles size={14} /> Объяснение ИИ
          </div>
          <p className="text-slate-800">{finding.summary}</p>
          {finding.causes.length > 0 && (
            <>
              <SectionTitle>
                <span className="mt-4 block">Вероятные причины</span>
              </SectionTitle>
              <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
                {finding.causes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card className="p-4">
          <SectionTitle>Что сделать</SectionTitle>
          <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-700">
            {finding.actions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ol>
          {experiment?.progress && <div className="mt-4 rounded-md bg-blue-50 p-3 text-sm text-blue-900">{experiment.progress}</div>}
        </Card>
      </div>

      {finding.chart && (
        <Card className="mt-6 p-4">
          <TrendChart spec={finding.chart} restaurantLabel={restaurant ? "Ваш ресторан" : "Ресторан"} />
        </Card>
      )}

      {finding.evidence && (
        <Card className="mt-6 overflow-x-auto p-4">
          <SectionTitle aside="исходные данные">Доказательства: {finding.evidence.title}</SectionTitle>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500">
              <tr>
                {finding.evidence.columns.map((c, i) => (
                  <th key={c} className={`py-1 pr-4 font-normal ${i > 0 ? "text-right" : ""}`}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {finding.evidence.rows.map((row, r) => (
                <tr key={r} className={`border-t border-slate-100 ${r === finding.evidence!.rows.length - 1 && finding.kind === "problem" ? "font-semibold" : ""}`}>
                  {row.map((cell, c) => (
                    <td key={c} className={`py-1.5 pr-4 ${c > 0 ? "text-right" : ""}`}>
                      {typeof cell === "number" ? num(cell) : cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
