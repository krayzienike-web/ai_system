import { CheckCircle2 } from "lucide-react";

import { VerifiedNote } from "../../ds/ai";
import { Card, PageTitle, QuestionBlock, Reveal } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend } from "../../ds/viz";
import { perMonth, rub, thousands } from "../../lib/format";
import { EXPERIMENTS, FINDINGS, PERIOD } from "../../mock/data";
import { networkTotals, networkTrend } from "../../mock/selectors";
import { usePrototype } from "../../state/prototype";

/** One page for the owner or investor: found / taken into work / returned. */
export function ReportPage() {
  const { findingStatus } = usePrototype();
  const totals = networkTotals();
  const trend = networkTrend();
  const found = totals.losses + totals.potential;
  const inWork = FINDINGS.filter((f) => ["in_work", "in_experiment"].includes(findingStatus[f.id] ?? f.status)).reduce(
    (acc, f) => acc + (f.effectRubMonth ?? 0),
    0,
  );
  const figures = [
    { label: "Нашли", value: found, note: "можно добавить к прибыли по открытым находкам", tone: "text-ink" },
    { label: "Взяли в работу", value: inWork, note: "задачи и проверки идут", tone: "text-brand-strong" },
    { label: "Уже добавили к прибыли", value: totals.confirmed, note: "подтверждено проверками", tone: "text-gain" },
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
          <AreaTrend labels={trend.labels} series={[{ name: "Можно добавить к прибыли", values: trend.onTable, color: "#0a8f84", fill: true }]} format={rub} height={140} />
        </QuestionBlock>
      </Reveal>
      <Reveal index={2}>
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
