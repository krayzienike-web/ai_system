import { CheckCircle2, XCircle } from "lucide-react";

import { VerifiedNote } from "../../ds/ai";
import { Card, PageTitle, QuestionBlock, Reveal } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend } from "../../ds/viz";
import { num, perMonth, plural, rub } from "../../lib/format";
import { EXPERIMENTS, FINDINGS, PERIOD } from "../../mock/data";
import { networkTotals, networkTrend, restaurantByCode, trendInPeriod } from "../../mock/selectors";
import { useUi } from "../../state/ui";
import { usePeriod, useTasks } from "../counts";
import { OutcomePill } from "../tasks/trace";

/** One page for the head of the network: found / taken into work / confirmed. */
export function ReportPage() {
  const { findingStatus } = useUi();
  const tasks = useTasks();
  const doneTasks = tasks.filter((t) => t.status === "done");
  // What did not work or was not done: failed checks, tasks without effect, overdue tasks.
  const failures = [
    ...EXPERIMENTS.filter((e) => e.result && e.result.verdict !== "confirmed").map((e) => ({
      key: e.id,
      title: `Проверка «${e.title}»`,
      where: e.test.map((c) => restaurantByCode(c)?.name).join(", "),
      why: e.result!.text,
      verdict: e.result!.verdict === "rejected" ? "не сработало" : "непонятно",
      tone: "text-loss",
    })),
    ...doneTasks
      .filter((t) => t.outcome?.verdict === "not_confirmed" && !t.experimentId)
      .map((t) => ({ key: t.id, title: t.title, where: restaurantByCode(t.restaurantId)?.name ?? "", why: t.outcome!.text, verdict: "не сработало", tone: "text-loss" })),
    ...tasks
      .filter((t) => t.status === "overdue")
      .map((t) => ({ key: t.id, title: t.title, where: restaurantByCode(t.restaurantId)?.name ?? "", why: `срок был ${t.due}`, verdict: "не сделано в срок", tone: "text-warn" })),
  ];
  const taskConfirmed = doneTasks.reduce((acc, t) => acc + (t.outcome?.verdict === "confirmed" ? (t.outcome.effectRubMonth ?? 0) : 0), 0);
  const totals = networkTotals();
  const period = usePeriod();
  const trend = trendInPeriod(networkTrend(), period.from, period.to);
  const span = plural(trend.labels.length - 1, ["неделю", "недели", "недель"]);
  const [firstValue, lastValue] = [trend.onTable[0]!, trend.onTable.at(-1)!];
  const [openBefore, openNow] = [trend.openFindings[0]!, trend.openFindings.at(-1)!];
  const found = totals.losses + totals.potential;
  const inWork = FINDINGS.filter((f) => ["in_work", "in_experiment"].includes(findingStatus[f.id] ?? f.status)).reduce(
    (acc, f) => acc + (f.effectRubMonth ?? 0),
    0,
  );
  const figures = [
    { label: "Найденный потенциал прибыли", value: found, note: "по открытым находкам", tone: "text-ink" },
    { label: "В работе", value: inWork, note: "задачи и проверки идут", tone: "text-brand-strong" },
    { label: "Подтвержденный эффект", value: totals.confirmed, note: "по итогам завершенных проверок", tone: "text-gain" },
  ];

  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <PageTitle title="Отчет для руководителя" subtitle={`Сеть «Демо-сеть» · данные по ${PERIOD.dataUntil}`} />
      <Reveal>
        <div className="grid gap-4 sm:grid-cols-3">
          {figures.map((f) => (
            <Card key={f.label} className="p-6">
              <div className="text-sm font-medium text-ink-3">{f.label}</div>
              <div className={`num mt-2 font-display text-[36px] leading-none font-semibold whitespace-nowrap ${f.tone}`}>
                <AnimatedNumber value={f.value} format={(n) => `${num(Math.round(n))} ₽`} />
              </div>
              <div className="mt-1 text-sm text-ink-2">в месяц</div>
              <div className="mt-3 text-xs text-ink-3">
                {f.note} · {num(Math.round(f.value * 12))} ₽ в год
              </div>
            </Card>
          ))}
        </div>
      </Reveal>
      <Reveal index={1}>
        <QuestionBlock
          question="Какая динамика по находкам?"
          answer={`За ${span} найденный потенциал ${lastValue <= firstValue ? "снизился" : "вырос"} с ${num(firstValue)} ₽ до ${num(lastValue)} ₽ в месяц, открытых находок — ${openNow} (было ${openBefore}).`}
          source={<VerifiedNote>оценка на конец каждой недели, {period.label.toLowerCase()}</VerifiedNote>}
        >
          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Открытых находок", value: `${openNow}`, note: `было ${openBefore}` },
              { label: "Закрыто находок", value: `${Math.max(0, openBefore - openNow)}`, note: "исправлены или подтверждены проверкой" },
              {
                label: "Найденный потенциал",
                value: `${lastValue <= firstValue ? "−" : "+"}${num(Math.abs(lastValue - firstValue))} ₽`,
                note: `в месяц, за ${span}`,
              },
            ].map((x) => (
              <div key={x.label} className="rounded-[12px] bg-paper p-4">
                <div className="text-xs text-ink-3">{x.label}</div>
                <div className="num mt-1 font-display text-2xl font-semibold">{x.value}</div>
                <div className="text-xs text-ink-3">{x.note}</div>
              </div>
            ))}
          </div>
          <AreaTrend labels={trend.labels} series={[{ name: "Найденный потенциал", values: trend.onTable, color: "#0a8f84", fill: true }]} format={rub} height={140} />
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
        <QuestionBlock
          question="Что не получилось?"
          answer={
            failures.length
              ? `${plural(failures.length, ["пункт требует", "пункта требуют", "пунктов требуют"])} внимания: что не сработало и что не сделано в срок.`
              : "Все задачи выполнены в срок, неудачных проверок нет."
          }
          source={<VerifiedNote>результат проверок и задач посчитан по данным; просрочка — по сроку задачи</VerifiedNote>}
        >
          <ul className="divide-y divide-line">
            {failures.map((x) => (
              <li key={x.key} className="grid gap-x-4 gap-y-1 py-3 text-sm sm:grid-cols-[1fr_auto]">
                <span className="min-w-0">
                  <span className="block font-medium">{x.title}</span>
                  <span className="block text-ink-3">
                    {x.where} · {x.why}
                  </span>
                </span>
                <span className={`inline-flex items-center gap-1 self-start font-semibold ${x.tone}`}>
                  <XCircle size={15} /> {x.verdict}
                </span>
              </li>
            ))}
          </ul>
        </QuestionBlock>
      </Reveal>
      <Reveal index={4}>
        <QuestionBlock question="Что проверили?" answer="Каждая мера сначала проверяется на части ресторанов — в сеть идет только то, что сработало.">
          <ul className="space-y-3">
            {EXPERIMENTS.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start justify-between gap-2 rounded-[12px] bg-paper p-4">
                <div>
                  <div className="font-medium">{e.title}</div>
                  <div className="text-sm text-ink-3">{e.hypothesis}</div>
                </div>
                <div className="text-sm">
                  {e.result?.verdict === "confirmed" ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-gain">
                      <CheckCircle2 size={15} /> +{perMonth(e.result.effectRubMonth)}
                    </span>
                  ) : e.result ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-loss">
                      <XCircle size={15} /> не сработало
                    </span>
                  ) : (
                    <span className="text-ink-2">{e.status === "running" ? "идет" : "ждет запуска"} · ожидаем +{perMonth(e.expectedRubMonth)}</span>
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
