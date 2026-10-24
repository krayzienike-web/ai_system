import { CheckCircle2 } from "lucide-react";

import { VerifiedNote } from "../../ds/ai";
import { Card, PageTitle, QuestionBlock, Reveal } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend } from "../../ds/viz";
import { perMonth, rub, thousands } from "../../lib/format";
import { EXPERIMENTS, FINDINGS, PERIOD } from "../../mock/data";
import { networkTotals, networkTrend, restaurantByCode } from "../../mock/selectors";
import { usePrototype } from "../../state/prototype";
import { useTasks } from "../counts";
import { OutcomePill } from "../tasks/trace";

/** One page for the owner or investor: found / taken into work / returned. */
export function ReportPage() {
  const { findingStatus } = usePrototype();
  const tasks = useTasks();
  const doneTasks = tasks.filter((t) => t.status === "done");
  const taskConfirmed = doneTasks.reduce((acc, t) => acc + (t.outcome?.verdict === "confirmed" ? (t.outcome.effectRubMonth ?? 0) : 0), 0);
  const totals = networkTotals();
  const trend = networkTrend();
  const found = totals.losses + totals.potential;
  const inWork = FINDINGS.filter((f) => ["in_work", "in_experiment"].includes(findingStatus[f.id] ?? f.status)).reduce(
    (acc, f) => acc + (f.effectRubMonth ?? 0),
    0,
  );
  const figures = [
    { label: "Потенциал прибыли", value: found, note: "по открытым находкам", tone: "text-ink" },
    { label: "В работе", value: inWork, note: "задачи и проверки идут", tone: "text-brand-strong" },
    { label: "Подтвержденный эффект", value: totals.confirmed, note: "по итогам завершенных проверок", tone: "text-gain" },
  ];

  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <PageTitle title="Отчет для собственника" subtitle={`Сеть «Демо-сеть» · данные по ${PERIOD.dataUntil}`} />
      <Reveal>
        <div className="grid gap-4 sm:grid-cols-3">
          {figures.map((f) => (
            <Card key={f.label} className="p-6">
              <div className="text-sm font-medium text-ink-3">{f.label}</div>
              <div className={`mt-2 font-display text-[44px] leading-none font-semibold ${f.tone}`}>
                <AnimatedNumber value={f.value} format={thousands} />
              </div>
              <div className="mt-1 text-sm text-ink-2">тыс ₽ в месяц</div>
              <div className="mt-3 text-xs text-ink-3">
                {f.note} · ≈ {rub(f.value * 12)} в год
              </div>
            </Card>
          ))}
        </div>
      </Reveal>
      <Reveal index={1}>
        <QuestionBlock
          question="Какая динамика?"
          answer={`За 8 недель потери и упущенная выгода сократились с ${rub(trend.onTable[0]!)} до ${rub(found)} в месяц: часть проблем исправлена.`}
          source={<VerifiedNote>оценка на конец каждой недели</VerifiedNote>}
        >
          <AreaTrend labels={trend.labels} series={[{ name: "Потенциал прибыли", values: trend.onTable, color: "#0a8f84", fill: true }]} format={rub} height={140} />
        </QuestionBlock>
      </Reveal>
      <Reveal index={2}>
        <QuestionBlock
          question="Что сделали и что получилось?"
          answer={`Поставлено задач — ${tasks.length}, выполнено — ${doneTasks.length}. Подтверждено по данным: +${perMonth(taskConfirmed)}.`}
          source={<VerifiedNote>результат каждой задачи посчитан по данным после выполнения</VerifiedNote>}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-left text-xs text-ink-3">
                <tr className="border-b border-line">
                  <th className="py-2 pr-4 font-medium">Задача</th>
                  <th className="py-2 pr-4 font-medium">Ресторан</th>
                  <th className="py-2 pr-4 font-medium">Поставили → сделали</th>
                  <th className="py-2 font-medium">Результат</th>
                </tr>
              </thead>
              <tbody>
                {doneTasks.map((t) => (
                  <tr key={t.id} className="border-b border-line align-top last:border-0">
                    <td className="py-3 pr-4">
                      <div className="font-medium">{t.title}</div>
                      {t.report && <div className="mt-0.5 text-xs text-ink-3">Отчет: {t.report}</div>}
                    </td>
                    <td className="py-3 pr-4 text-ink-2">{restaurantByCode(t.restaurantId)?.name}</td>
                    <td className="num py-3 pr-4 text-ink-2">
                      {t.createdAt} → {t.doneAt}
                    </td>
                    <td className="py-3">
                      <OutcomePill outcome={t.outcome} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </QuestionBlock>
      </Reveal>
      <Reveal index={3}>
        <QuestionBlock question="Что проверили?" answer="Каждая мера сначала проверяется на части ресторанов — в сеть идет только то, что сработало.">
          <ul className="space-y-3">
            {EXPERIMENTS.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start justify-between gap-2 rounded-[12px] bg-paper p-4">
                <div>
                  <div className="font-medium">{e.title}</div>
                  <div className="text-sm text-ink-3">{e.hypothesis}</div>
                </div>
                <div className="text-sm">
                  {e.result ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-gain">
                      <CheckCircle2 size={15} /> +{perMonth(e.result.effectRubMonth)}
                    </span>
                  ) : (
                    <span className="text-ink-2">{e.status === "running" ? "идет" : "ждет решения"} · ожидаем +{perMonth(e.expectedRubMonth)}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </QuestionBlock>
      </Reveal>
    </div>
  );
}
