import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, ChevronDown, FlaskConical, MessageCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { useAppContext, useFinding } from "../../api/hooks";
import type { FindingDetail } from "../../api/types";
import { TrendChart } from "../../ds/TrendChart";
import { VerifiedNote } from "../../ds/ai";
import { SourceDocuments } from "./Sources";
import { Button, buttonClass, Card, EmptyState, Pill, QuestionBlock, Reveal, Skeleton } from "../../ds/primitives";
import { BulletScale, CompositionBar, CycleSteps } from "../../ds/viz";
import { ddmm, money, num, perMonth, rub } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";
import { QuickSteps, TaskTrace } from "../tasks/trace";
import { FindingConfidence, MoneyWords, ProcessChip, STAGE_INDEX, TakeToWorkDialog } from "./parts";
import { ReviewTrace } from "./ReviewTrace";

export function FindingPage() {
  const { findingId } = useParams({ from: "/app/findings/$findingId" });
  const viewer = useViewer();
  const finding = useFinding(findingId);
  if (!viewer) return null;
  if (finding.isError) {
    // The API answers «not found» both for a missing finding and for another restaurant's one.
    return <EmptyState title="Находка не найдена">Возможно, она относится к другому ресторану или ее уже нет в данных.</EmptyState>;
  }
  if (!finding.data) return <Skeleton className="mx-auto h-96 max-w-[1040px]" />;
  return <FindingView key={finding.data.id} f={finding.data} isHq={viewer.isHq} />;
}

function FindingView({ f, isHq }: { f: FindingDetail; isHq: boolean }) {
  const { openChat } = useUi();
  const context = useAppContext();
  const [taking, setTaking] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const view = f.view;
  const check = f.check;
  const effect = money(f.effect_rub_month);
  const scale = view?.scale;
  const fmtScale = (n: number) => (scale?.unit === "%" ? `${n.toLocaleString("ru-RU")}%` : `${num(n)} ${scale?.unit ?? ""}`);

  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <Link to={isHq ? "/findings" : "/"} className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> {isHq ? "Все находки" : "Моя неделя"}
      </Link>

      {/* Header: what, how much, where in the loop */}
      <Reveal>
        <section className="rounded-[24px] border border-line bg-surface p-6 sm:p-8">
          <div className="flex flex-wrap items-center gap-3">
            <Pill tone={f.kind === "problem" ? "loss" : "gain"}>{f.kind === "problem" ? "Проблема" : "Возможность"}</Pill>
            <ProcessChip f={f} />
            <span className="text-xs text-ink-3">{f.restaurant_name ?? "Вся сеть"}</span>
          </div>
          <h1 className="mt-3 font-display text-[26px] leading-tight font-semibold sm:text-[32px]">{f.title}</h1>
          <div className="mt-2">
            <MoneyWords f={f} size="lg" />
            {f.effect_rub_year !== null && <span className="text-sm text-ink-3"> · около {rub(money(f.effect_rub_year) ?? 0)} в год</span>}
          </div>
          <p className="mt-4 max-w-[70ch] text-[17px] leading-relaxed text-ink">{f.headline ?? view?.summary}</p>
          <div className="mt-6 max-w-xl">
            <CycleSteps
              current={STAGE_INDEX[f.work.stage]}
              notes={[undefined, f.work.tasks_total ? "задача поставлена" : undefined, check?.status === "running" ? `до ${ddmm(check.ends_on)}` : undefined]}
            />
          </div>
          {f.module && (
            <div className="mt-5 border-t border-line pt-4">
              <ReviewTrace f={f} compact />
            </div>
          )}
          <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-line pt-5">
            {!isHq && f.work.stage === "new" && (
              <Button variant="primary" size="lg" onClick={() => setTaking(true)}>
                Взять в работу
              </Button>
            )}
            {isHq && f.restaurant_id && !check && (
              <Link to="/checks/new/$findingId" params={{ findingId: f.id }} className={buttonClass("primary", "lg")}>
                <FlaskConical size={16} /> Проверить на части ресторанов
              </Link>
            )}
            {isHq && check && (
              <Link to="/checks/$checkId" params={{ checkId: check.id }} className={buttonClass("secondary", "lg")}>
                <FlaskConical size={16} /> Проверка: {check.title}
              </Link>
            )}
            <Button variant="ghost" size="lg" onClick={() => openChat({ title: f.title, findingId: f.id })}>
              <MessageCircle size={16} /> Спросить су-шефа
            </Button>
            <span className="ml-auto">
              <FindingConfidence f={f} />
            </span>
          </div>
          {check?.progress_text && check.status === "running" && (
            <div className="mt-4 rounded-[12px] bg-info-soft p-4 text-sm text-info">{check.progress_text}</div>
          )}
        </section>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-2">
        {scale && scale.me !== null && (
          <Reveal index={1}>
            <QuestionBlock
              question="Это много?"
              answer={scale.answer}
              source={view?.confidence_note && <VerifiedNote>{view.confidence_note}</VerifiedNote>}
              className="h-full"
            >
              <div className="text-sm font-medium">{scale.label}</div>
              <BulletScale
                me={scale.me}
                network={scale.network ?? undefined}
                norm={scale.norm ?? undefined}
                lowerIsBetter={scale.lower_is_better}
                format={fmtScale}
                meLabel={isHq ? "Ресторан" : "Вы"}
                networkLabel={scale.network_label ?? "Сеть"}
              />
              {scale.network_label && <p className="-mt-2 text-xs text-ink-3">Оранжевая отметка — {scale.network_label.toLowerCase()}.</p>}
            </QuestionBlock>
          </Reveal>
        )}

        <Reveal index={2}>
          <QuestionBlock
            question="Почему так и что сделать?"
            answer="Вероятные причины"
            source={<VerifiedNote>типовые причины для такой находки — проверьте на месте; объяснение ИИ по вашим данным появится с помощником аналитика</VerifiedNote>}
            className="h-full"
          >
            {!!view?.causes?.length && (
              <ul className="space-y-2 text-sm text-ink-2">
                {view.causes.map((c) => (
                  <li key={c} className="flex gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-3" aria-hidden />
                    {c}
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-5">
              <QuickSteps f={f} tasks={f.tasks} />
            </div>
          </QuestionBlock>
        </Reveal>
      </div>

      {f.result_answer && (
        <Reveal index={3}>
          <QuestionBlock
            question="Что сделали и что получилось?"
            answer={f.result_answer}
            source={<VerifiedNote>результат считает система по данным после выполнения, а не со слов исполнителя</VerifiedNote>}
          >
            <div className="grid gap-4 md:grid-cols-2">
              {f.tasks.map((t) => (
                <div key={t.id} className="rounded-[16px] border border-line p-4">
                  <div className="mb-3 font-medium">{isHq && t.restaurant_name ? `${t.restaurant_name}: ${t.title}` : t.title}</div>
                  <TaskTrace task={t} showFinding={false} showRestaurant={isHq} />
                </div>
              ))}
              {check && (
                <Link to="/checks/$checkId" params={{ checkId: check.id }} className="rounded-[16px] border border-line p-4 transition hover:border-ink-3">
                  <div className="flex items-center gap-2 font-medium">
                    <FlaskConical size={16} className="text-brand" /> Проверка «{check.title}»
                  </div>
                  <div className="mt-2 text-sm text-ink-2">
                    {check.verdict === "confirmed" && money(check.effect_rub_month)
                      ? `Итог: +${perMonth(money(check.effect_rub_month)!)} — подтверждено сравнением с ресторанами без изменений.`
                      : (check.progress_text ?? `Ожидаем +${perMonth(money(check.expected_rub_month) ?? 0)}; итог — после ${ddmm(check.ends_on)}.`)}
                  </div>
                  <div className="mt-2 text-sm text-brand-strong">Открыть проверку →</div>
                </Link>
              )}
            </div>
          </QuestionBlock>
        </Reveal>
      )}

      {view?.composition && (
        <Reveal index={3}>
          <QuestionBlock question="Из чего сложилась потеря?" answer={view.composition.answer} source={<VerifiedNote>{view.composition.formula}</VerifiedNote>}>
            <CompositionBar
              parts={view.composition.parts.map((p) => ({ ...p, value: p.value ?? 0, tone: p.tone as "brand" | "neutral" | "loss" | "gain" }))}
              format={(n) => `${num(n)} ${view.composition!.unit}`}
            />
          </QuestionBlock>
        </Reveal>
      )}

      {view?.chart && (
        <Reveal index={4}>
          <QuestionBlock question="Как это менялось?" answer={view.chart.conclusion}>
            <TrendChart spec={view.chart} restaurantLabel={isHq ? "Ресторан" : "Ваш ресторан"} />
          </QuestionBlock>
        </Reveal>
      )}

      {view?.table && (
        <Reveal index={5}>
          <Card>
            <button
              type="button"
              onClick={() => setShowEvidence((v) => !v)}
              aria-expanded={showEvidence}
              className="flex w-full items-center justify-between px-6 py-4 text-left"
            >
              <span>
                <span className="block text-[13px] font-semibold tracking-[0.06em] text-ink-3 uppercase">Откуда цифры</span>
                <span className="font-medium">{view.table.title}</span>
              </span>
              <ChevronDown size={18} className={showEvidence ? "rotate-180 transition" : "transition"} />
            </button>
            <AnimatePresence initial={false}>
              {showEvidence && (
                <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
                  <div className="overflow-x-auto px-6 pb-5">
                    <table className="w-full text-sm">
                      <thead className="text-left text-ink-3">
                        <tr>
                          {view.table.columns.map((c, i) => (
                            <th key={c} className={`py-2 pr-4 font-medium ${i ? "text-right" : ""}`}>
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="num">
                        {view.table.rows.map((row, r) => (
                          <tr key={r} className="border-t border-line">
                            {row.map((cell, c) => (
                              <td key={c} className={`py-2 pr-4 ${c ? "text-right" : ""}`}>
                                {typeof cell === "number" ? num(cell) : (cell ?? "—")}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </Card>
        </Reveal>
      )}

      <Reveal index={7}>
        <SourceDocuments findingId={f.id} />
      </Reveal>

      <p className="text-xs text-ink-3">
        {context.data?.data_until && <>Данные по {ddmm(context.data.data_until)}. </>}
        {effect !== null && `Сумма ${perMonth(effect)} — оценка до уровня среднего по сети, а не до идеала.`}
      </p>

      <TakeToWorkDialog f={f} open={taking} onClose={() => setTaking(false)} />
    </div>
  );
}
