import { CheckCircle2, XCircle } from "lucide-react";

import { useAppContext, useHeadReport } from "../../api/hooks";
import { VerifiedNote } from "../../ds/ai";
import { Card, PageTitle, QuestionBlock, Reveal, Skeleton } from "../../ds/primitives";
import { AnimatedNumber, AreaTrend } from "../../ds/viz";
import { ddmm, money, num, perMonth, plural, rub } from "../../lib/format";
import { useUi } from "../../state/ui";
import { OutcomePill } from "../tasks/trace";

const VERDICT_WORD: Record<string, string> = {
  check_no_effect: "не сработало",
  task_no_effect: "не сработало",
  task_overdue: "не сделано в срок",
};

/** One page for the head of the network: found / taken into work / confirmed. Every figure comes from the API. */
export function ReportPage() {
  const { period } = useUi();
  const report = useHeadReport(period);
  const context = useAppContext();
  const r = report.data;
  if (!r) return <Skeleton className="mx-auto h-[600px] max-w-[1040px]" />;

  const trend = r.trend.on_table.map((v) => money(v) ?? 0);
  const [firstValue, lastValue] = [trend[0] ?? 0, trend.at(-1) ?? 0];
  const span = plural(Math.max(trend.length - 1, 1), ["неделю", "недели", "недель"]);
  const confirmedByTasks = money(r.confirmed_by_tasks_rub_month) ?? 0;
  const figures = [
    { label: "Найденный потенциал прибыли", value: money(r.found_rub_month) ?? 0, note: "по открытым находкам", tone: "text-ink" },
    { label: "В работе", value: money(r.in_work_rub_month) ?? 0, note: "задачи и проверки идут", tone: "text-brand-strong" },
    { label: "Подтвержденный эффект", value: money(r.confirmed_rub_month) ?? 0, note: "по итогам проверок и задач", tone: "text-gain" },
  ];

  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <PageTitle
        title="Отчет для руководителя"
        subtitle={`Сеть «${r.network_name}» · ${ddmm(r.date_from)}–${ddmm(r.date_to)}${context.data?.data_until ? ` · данные по ${ddmm(context.data.data_until)}` : ""}`}
      />
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
          answer={
            trend.length < 2
              ? `Открытых находок — ${r.open_findings_now}. История появится после двух недель пересчетов.`
              : `За ${span} найденный потенциал ${lastValue <= firstValue ? "снизился" : "вырос"} с ${num(firstValue)} ₽ до ${num(lastValue)} ₽ в месяц, открытых находок — ${r.open_findings_now} (было ${r.open_findings_before}).`
          }
          source={<VerifiedNote>оценка на конец каждой недели</VerifiedNote>}
        >
          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            {[
              { label: "Открытых находок", value: `${r.open_findings_now}`, note: `было ${r.open_findings_before}` },
              { label: "Закрыто находок", value: `${r.closed_findings}`, note: "исправлены или подтверждены проверкой" },
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
          <AreaTrend labels={r.trend.labels} series={[{ name: "Найденный потенциал", values: trend, color: "#0a8f84", fill: true }]} format={rub} height={140} />
        </QuestionBlock>
      </Reveal>
      <Reveal index={2}>
        <QuestionBlock
          question="Что сделали и что получилось?"
          answer={`Поставлено задач — ${r.tasks_set}, выполнено — ${r.tasks_done}. Подтверждено по данным: +${perMonth(confirmedByTasks)}.`}
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
                {r.done_tasks.map((t) => (
                  <tr key={t.id} className="border-b border-line align-top last:border-0">
                    <td className="py-3 pr-4">
                      <div className="font-medium">{t.title}</div>
                      {t.report && <div className="mt-0.5 text-xs text-ink-3">Отчет: {t.report}</div>}
                    </td>
                    <td className="py-3 pr-4 text-ink-2">{t.restaurant_name}</td>
                    <td className="num py-3 pr-4 text-ink-2">
                      {ddmm(t.created_on)} → {ddmm(t.done_on)}
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
            r.failures.length
              ? `${plural(r.failures.length, ["пункт требует", "пункта требуют", "пунктов требуют"])} внимания: что не сработало и что не сделано в срок.`
              : "Все задачи выполнены в срок, неудачных проверок нет."
          }
          source={<VerifiedNote>результат проверок и задач посчитан по данным; просрочка — по сроку задачи</VerifiedNote>}
        >
          <ul className="divide-y divide-line">
            {r.failures.map((x, i) => (
              <li key={`${x.kind}-${i}`} className="grid gap-x-4 gap-y-1 py-3 text-sm sm:grid-cols-[1fr_auto]">
                <span className="min-w-0">
                  <span className="block font-medium">{x.kind === "check_no_effect" ? `Проверка «${x.title}»` : x.title}</span>
                  <span className="block text-ink-3">
                    {x.where} · {x.reason}
                  </span>
                </span>
                <span className={`inline-flex items-center gap-1 self-start font-semibold ${x.kind === "task_overdue" ? "text-warn" : "text-loss"}`}>
                  <XCircle size={15} /> {VERDICT_WORD[x.kind] ?? x.kind}
                </span>
              </li>
            ))}
          </ul>
        </QuestionBlock>
      </Reveal>
      <Reveal index={4}>
        <QuestionBlock question="Что проверили?" answer="Каждая мера сначала проверяется на части ресторанов — в сеть идет только то, что сработало.">
          <ul className="space-y-3">
            {r.checks.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start justify-between gap-2 rounded-[12px] bg-paper p-4">
                <div>
                  <div className="font-medium">{e.title}</div>
                  <div className="text-sm text-ink-3">{e.hypothesis}</div>
                </div>
                <div className="text-sm">
                  {e.verdict === "confirmed" ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-gain">
                      <CheckCircle2 size={15} /> +{perMonth(money(e.effect_rub_month) ?? 0)}
                    </span>
                  ) : e.verdict ? (
                    <span className="inline-flex items-center gap-1 font-semibold text-loss">
                      <XCircle size={15} /> {e.verdict === "rejected" ? "не сработало" : "непонятно"}
                    </span>
                  ) : (
                    <span className="text-ink-2">
                      {e.status === "running" ? "идет" : e.status === "rejected" ? "отклонена" : "ждет запуска"} · ожидаем +{perMonth(money(e.expected_rub_month) ?? 0)}
                    </span>
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
