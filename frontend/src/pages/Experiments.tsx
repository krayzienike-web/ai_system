import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ArrowLeft, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button, Card, EmptyState, PageHeader, Pill, SectionTitle } from "../components/ui";
import { rubMonth } from "../lib/format";
import { EXPERIMENTS } from "../mock/data";
import { findingById, restaurantByCode } from "../mock/selectors";
import type { Experiment } from "../mock/types";
import { usePrototype } from "../state/prototype";

const names = (codes: string[]) => (codes.length ? codes.map((c) => restaurantByCode(c)?.name ?? c).join(", ") : "—");

function useExperimentStatus(e: Experiment) {
  const { experimentStatus } = usePrototype();
  const decision = experimentStatus[e.id];
  if (decision === "approved") return "Утвержден, задачи поставлены";
  if (decision === "rejected") return "Отклонен";
  return { proposed: "Ждет утверждения", running: "Идет", completed: "Завершен" }[e.status];
}

function ExperimentRow({ e }: { e: Experiment }) {
  const status = useExperimentStatus(e);
  return (
    <Link to="/experiments/$experimentId" params={{ experimentId: e.id }} className="block">
      <Card className="p-4 hover:border-slate-300">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="font-medium text-slate-900">{e.title}</div>
          <Pill tone={e.status === "completed" ? "gain" : e.status === "running" ? "info" : "neutral"}>{status}</Pill>
        </div>
        <div className="mt-1 text-sm text-slate-600">{e.hypothesis}</div>
        <div className="mt-2 text-xs text-slate-500">
          {e.design} · {e.period} ·{" "}
          {e.result ? `подтверждено ${rubMonth(e.result.effectRubMonth)}` : `ожидается ${rubMonth(e.expectedRubMonth)}`}
        </div>
      </Card>
    </Link>
  );
}

function DraftFromFinding({ findingId }: { findingId: string }) {
  const finding = findingById(findingId);
  const [sent, setSent] = useState(false);
  if (!finding || !finding.restaurantId) return null;
  const others = ["R01", "R02", "R03"].filter((c) => c !== finding.restaurantId);
  return (
    <Card className="mb-6 border-blue-200 p-4">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-blue-800">
        <Sparkles size={14} /> Черновик гипотезы от ИИ — проверьте и отправьте на утверждение
      </div>
      <div className="font-medium text-slate-900">{finding.actions[0]}</div>
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Гипотеза</dt>
          <dd>
            Если в ресторане «{restaurantByCode(finding.restaurantId)?.name}» выполнить меру «{finding.actions[0]}», показатель «
            {finding.metric.label.toLowerCase()}» приблизится к норме.
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Дизайн</dt>
          <dd>Тест — {restaurantByCode(finding.restaurantId)?.name}; контроль — {names(others)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Метрика успеха</dt>
          <dd>{finding.metric.label}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Ожидаемый эффект</dt>
          <dd>{rubMonth(Math.round(((finding.effectRubMonth ?? 0) * 0.6) / 100) * 100)} (60% от найденного, консервативно)</dd>
        </div>
      </dl>
      <div className="mt-4">
        {sent ? (
          <span className="text-sm text-emerald-700">Отправлено на утверждение руководителю УК.</span>
        ) : (
          <Button variant="primary" onClick={() => setSent(true)}>
            Отправить на утверждение
          </Button>
        )}
      </div>
    </Card>
  );
}

export function ExperimentsPage() {
  const { draft } = useSearch({ from: "/app/experiments" });
  const groups: [string, Experiment[]][] = [
    ["Ждут утверждения", EXPERIMENTS.filter((e) => e.status === "proposed")],
    ["Идут", EXPERIMENTS.filter((e) => e.status === "running")],
    ["Завершены", EXPERIMENTS.filter((e) => e.status === "completed")],
  ];
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Эксперименты" meta="Гипотеза → утверждение → задачи директорам → замер эффекта" />
      {draft && <DraftFromFinding findingId={draft} />}
      <div className="space-y-6">
        {groups.map(([title, items]) => (
          <section key={title}>
            <SectionTitle>{title}</SectionTitle>
            <div className="space-y-3">
              {items.length ? items.map((e) => <ExperimentRow key={e.id} e={e} />) : <EmptyState title="Нет экспериментов" />}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

export function ExperimentPage() {
  const { experimentId } = useParams({ from: "/app/experiments/$experimentId" });
  const navigate = useNavigate();
  const { experimentStatus, decideExperiment } = usePrototype();
  const [rolloutSent, setRolloutSent] = useState(false);
  const e = EXPERIMENTS.find((x) => x.id === experimentId);
  if (!e) return <EmptyState title="Эксперимент не найден" />;
  const decision = experimentStatus[e.id];
  const status = decision === "approved" ? "Утвержден" : decision === "rejected" ? "Отклонен" : { proposed: "Ждет утверждения", running: "Идет", completed: "Завершен" }[e.status];

  return (
    <div className="mx-auto max-w-4xl">
      <Link to="/experiments" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-600 hover:underline">
        <ArrowLeft size={14} /> Эксперименты
      </Link>
      <PageHeader title={e.title} meta={status} />

      <Card className="mb-6 p-4">
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div className="sm:col-span-2">
            <dt className="text-slate-500">Гипотеза</dt>
            <dd className="text-slate-900">{e.hypothesis}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Дизайн</dt>
            <dd>{e.design}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Метрика</dt>
            <dd>{e.metric}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Тестовая группа</dt>
            <dd>{names(e.test)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Контрольная группа</dt>
            <dd>{e.control.length ? names(e.control) : "внутри ресторана"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Базовый период</dt>
            <dd>{e.baseline}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Срок</dt>
            <dd>{e.period}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Ожидаемый эффект</dt>
            <dd className="font-medium">{rubMonth(e.expectedRubMonth)}</dd>
          </div>
          {e.findingId && (
            <div>
              <dt className="text-slate-500">Основание</dt>
              <dd>
                <Link to="/insights/$findingId" params={{ findingId: e.findingId }} className="underline">
                  {findingById(e.findingId)?.title}
                </Link>
              </dd>
            </div>
          )}
        </dl>
      </Card>

      {e.status === "proposed" && !decision && (
        <Card className="mb-6 p-4">
          <SectionTitle>Решение руководителя</SectionTitle>
          <p className="mb-3 text-sm text-slate-600">
            После утверждения директорам тестовых ресторанов ({names(e.test)}) будут поставлены задачи со сроком и чек-листом.
            Замер эффекта начнется автоматически.
          </p>
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => decideExperiment(e.id, "approved")}>
              Утвердить и поставить задачи
            </Button>
            <Button onClick={() => decideExperiment(e.id, "rejected")}>Отклонить</Button>
          </div>
        </Card>
      )}
      {decision === "approved" && (
        <Card className="mb-6 border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
          Утверждено. Задачи поставлены директорам: {names(e.test)}. Замер — с {e.period.replace("4 недели, с ", "")}.
          <Button variant="ghost" className="ml-2" onClick={() => navigate({ to: "/tasks" })}>
            Открыть задачи
          </Button>
        </Card>
      )}

      {e.progress && (
        <Card className="mb-6 p-4">
          <SectionTitle>Ход эксперимента</SectionTitle>
          <p className="text-sm text-slate-700">{e.progress}</p>
        </Card>
      )}

      {e.result && (
        <Card className="mb-6 p-4">
          <SectionTitle>Результат</SectionTitle>
          <div className="mb-3 flex flex-wrap items-baseline gap-3">
            <Pill tone="gain">Подтверждено</Pill>
            <span className="text-2xl font-semibold tabular-nums text-emerald-700">+{rubMonth(e.result.effectRubMonth)}</span>
            <span className="text-sm text-slate-500">
              интервал {rubMonth(e.result.ciLow)} – {rubMonth(e.result.ciHigh)}
            </span>
          </div>
          <EffectInterval low={e.result.ciLow} high={e.result.ciHigh} value={e.result.effectRubMonth} expected={e.expectedRubMonth} />
          <p className="mt-3 text-sm text-slate-700">{e.result.text}</p>
          {e.result.rolloutRubMonth && (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md bg-slate-50 p-3 text-sm">
              Тиражирование на остальные рестораны: потенциал {rubMonth(e.result.rolloutRubMonth)}
              {rolloutSent ? (
                <span className="text-emerald-700">Гипотеза тиражирования отправлена на утверждение.</span>
              ) : (
                <Button variant="primary" onClick={() => setRolloutSent(true)}>
                  Предложить тиражирование
                </Button>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/** Effect with its confidence interval on a shared ₽ scale, expected effect as a reference tick. */
function EffectInterval({ low, high, value, expected }: { low: number; high: number; value: number; expected: number }) {
  const max = Math.max(high, expected) * 1.15;
  const x = (v: number) => `${(v / max) * 100}%`;
  return (
    <div className="relative h-10" role="img" aria-label={`Эффект ${value} ₽, интервал ${low}–${high} ₽, ожидался ${expected} ₽`}>
      <div className="absolute top-4 h-0.5 w-full bg-slate-200" />
      <div className="absolute top-3 h-2.5 rounded-full bg-emerald-200" style={{ left: x(low), width: `calc(${x(high)} - ${x(low)})` }} />
      <div className="absolute top-2 h-4.5 w-1 rounded bg-emerald-700" style={{ left: x(value) }} />
      <div className="absolute top-1 h-6 w-px border-l border-dashed border-slate-500" style={{ left: x(expected) }} />
      <div className="absolute top-7 -translate-x-1/2 text-[11px] text-slate-500" style={{ left: x(expected) }}>
        ожидали
      </div>
    </div>
  );
}
