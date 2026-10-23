import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, ChevronDown, FlaskConical, MessageCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { TrendChart } from "../../ds/TrendChart";
import { AiBadge, VerifiedNote } from "../../ds/ai";
import { Button, buttonClass, Card, EmptyState, Pill, QuestionBlock, Reveal } from "../../ds/primitives";
import { BulletScale, CompositionBar, CycleSteps } from "../../ds/viz";
import { num, perMonth, rub } from "../../lib/format";
import { canSeeRestaurant, useViewer } from "../../lib/useViewer";
import { EXPERIMENTS, PERIOD } from "../../mock/data";
import { cycleStage, findingById, restaurantByCode } from "../../mock/selectors";
import { usePrototype } from "../../state/prototype";
import { DisputeDialog, FindingConfidence, MoneyWords, ProcessChip, TakeToWorkDialog, useStatus } from "./parts";

export function FindingPage() {
  const { findingId } = useParams({ from: "/app/findings/$findingId" });
  const viewer = useViewer();
  const finding = findingById(findingId);
  if (!viewer) return null;
  // Same rule as the API: a director never sees another restaurant's findings.
  if (!finding || !canSeeRestaurant(viewer, finding.restaurantId)) {
    return <EmptyState title="Находка не найдена">Возможно, она относится к другому ресторану.</EmptyState>;
  }
  return <FindingView key={finding.id} id={finding.id} isHq={viewer.isHq} />;
}

function FindingView({ id, isHq }: { id: string; isHq: boolean }) {
  const f = findingById(id)!;
  const status = useStatus(f);
  const { openChat, disputes } = usePrototype();
  const [taking, setTaking] = useState(false);
  const [disputing, setDisputing] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const restaurant = f.restaurantId ? restaurantByCode(f.restaurantId) : null;
  const experiment = EXPERIMENTS.find((e) => e.findingId === f.id);
  const stage = cycleStage(status);
  const unit = f.scale?.unit ?? "";
  const fmtScale = (n: number) => (unit === "%" ? `${n.toLocaleString("ru-RU")}%` : `${num(n)} ${unit}`);
  const dispute = f.dispute ?? (disputes[f.id] ? { by: "Вы", date: "сегодня", ...disputes[f.id]! } : undefined);

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
            <span className="text-xs text-ink-3">{restaurant ? restaurant.name : "Вся сеть"}</span>
          </div>
          <h1 className="mt-3 font-display text-[26px] leading-tight font-semibold sm:text-[32px]">{f.title}</h1>
          <div className="mt-2">
            <MoneyWords f={f} size="lg" />
            {f.effectRubMonth !== null && <span className="text-sm text-ink-3"> · около {rub(f.effectRubMonth * 12)} в год</span>}
          </div>
          <p className="mt-4 max-w-[70ch] text-[17px] leading-relaxed text-ink">{f.headline ?? f.summary}</p>
          <div className="mt-6 max-w-xl">
            <CycleSteps
              current={stage}
              notes={[undefined, status === "in_work" ? "задача поставлена" : undefined, experiment?.status === "running" ? "до 10.11" : undefined]}
            />
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-line pt-5">
            {!isHq && status === "new" && (
              <>
                <Button variant="primary" size="lg" onClick={() => setTaking(true)}>
                  Взять в работу
                </Button>
                <Button size="lg" onClick={() => setDisputing(true)}>
                  Не согласен
                </Button>
              </>
            )}
            {isHq && f.restaurantId && !experiment && (
              <Link to="/checks/new/$findingId" params={{ findingId: f.id }} className={buttonClass("primary", "lg")}>
                <FlaskConical size={16} /> Проверить на части ресторанов
              </Link>
            )}
            {isHq && experiment && (
              <Link to="/checks/$checkId" params={{ checkId: experiment.id }} className={buttonClass("secondary", "lg")}>
                <FlaskConical size={16} /> Проверка: {experiment.title}
              </Link>
            )}
            <Button variant="ghost" size="lg" onClick={() => openChat({ title: f.title, findingId: f.id })}>
              <MessageCircle size={16} /> Спросить су-шефа
            </Button>
            <span className="ml-auto">
              <FindingConfidence f={f} />
            </span>
          </div>
          {dispute && (
            <div className="mt-4 rounded-[12px] bg-warn-soft p-4 text-sm text-ink">
              <div className="font-medium">
                {dispute.by} не согласен(а): «{dispute.reason}» · {dispute.date}
              </div>
              {dispute.comment && <div className="mt-1 text-ink-2">{dispute.comment}</div>}
            </div>
          )}
          {experiment?.progress && <div className="mt-4 rounded-[12px] bg-info-soft p-4 text-sm text-info">{experiment.progress}</div>}
        </section>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-2">
        {f.scale && (
          <Reveal index={1}>
            <QuestionBlock
              question="Это много?"
              answer={scaleAnswer(f.scale)}
              source={<VerifiedNote>{f.confidenceNote}</VerifiedNote>}
              className="h-full"
            >
              <div className="text-sm font-medium">{f.scale.label}</div>
              <BulletScale
                me={f.scale.me}
                network={f.scale.network}
                norm={f.scale.norm}
                lowerIsBetter={f.scale.lowerIsBetter}
                format={fmtScale}
                meLabel={isHq ? "Ресторан" : "Вы"}
                networkLabel={f.scale.networkLabel ?? "Сеть"}
              />
              {f.scale.networkLabel && <p className="-mt-2 text-xs text-ink-3">Оранжевая отметка — {f.scale.networkLabel.toLowerCase()}.</p>}
            </QuestionBlock>
          </Reveal>
        )}

        <Reveal index={2}>
          <QuestionBlock
            question="Почему так и что сделать?"
            answer={
              <span className="inline-flex items-center gap-2">
                Вероятные причины <AiBadge basis={`${f.confidenceNote}. Причины — гипотезы ИИ по данным, их стоит проверить на месте.`} />
              </span>
            }
            className="h-full"
          >
            {f.causes.length > 0 && (
              <ul className="space-y-2 text-sm text-ink-2">
                {f.causes.map((c) => (
                  <li key={c} className="flex gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-3" aria-hidden />
                    {c}
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-5 text-sm font-medium">Что сделать</div>
            <ol className="mt-2 space-y-2 text-sm">
              {f.actions.map((a, i) => (
                <li key={a} className="flex gap-3">
                  <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand-strong">
                    {i + 1}
                  </span>
                  <span className="pt-0.5">{a}</span>
                </li>
              ))}
            </ol>
          </QuestionBlock>
        </Reveal>
      </div>

      {f.composition && (
        <Reveal index={3}>
          <QuestionBlock
            question="Из чего сложилась потеря?"
            answer={
              <>
                Из израсходованного <span className="num">{num(f.composition.parts.reduce((a, p) => a + p.value, 0))}</span> {f.composition.unit} почти все ушло
                по техкартам, но <span className="text-loss">{num(f.composition.parts.at(-1)!.value)} {f.composition.unit}</span> ничем не объяснены.
              </>
            }
            source={<VerifiedNote>{f.composition.formula}</VerifiedNote>}
          >
            <CompositionBar parts={f.composition.parts} format={(n) => `${num(n)} ${f.composition!.unit}`} />
          </QuestionBlock>
        </Reveal>
      )}

      {f.chart && (
        <Reveal index={4}>
          <QuestionBlock question="Как это менялось?" answer={f.chart.conclusion}>
            <TrendChart spec={f.chart} restaurantLabel={isHq ? "Ресторан" : "Ваш ресторан"} />
          </QuestionBlock>
        </Reveal>
      )}

      {f.evidence && (
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
                <span className="font-medium">{f.evidence.title} — документы по строкам</span>
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
                          {f.evidence.columns.map((c, i) => (
                            <th key={c} className={`py-2 pr-4 font-medium ${i ? "text-right" : ""}`}>
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="num">
                        {f.evidence.rows.map((row, r) => (
                          <tr key={r} className="border-t border-line">
                            {row.map((cell, c) => (
                              <td key={c} className={`py-2 pr-4 ${c ? "text-right" : ""}`}>
                                {typeof cell === "number" ? num(cell) : cell}
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

      <p className="text-xs text-ink-3">
        Данные по {PERIOD.dataUntil}. {f.effectRubMonth !== null && `Сумма ${perMonth(f.effectRubMonth)} — оценка до уровня среднего по сети, а не до идеала.`}
      </p>

      <TakeToWorkDialog f={f} open={taking} onClose={() => setTaking(false)} />
      <DisputeDialog f={f} open={disputing} onClose={() => setDisputing(false)} />
    </div>
  );
}

function scaleAnswer(s: NonNullable<ReturnType<typeof findingById>>["scale"]) {
  if (!s) return null;
  const ref = s.network ?? s.norm;
  if (ref === undefined) return null;
  const refName = s.network !== undefined ? (s.networkLabel ?? "среднее по сети").toLowerCase() : "норма";
  const worse = s.lowerIsBetter ? s.me > ref : s.me < ref;
  const ratio = s.me / ref;
  const diff =
    s.unit === "%"
      ? `на ${(s.me - ref).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} пункта`
      : ratio >= 1.5
        ? `в ${ratio.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} раза`
        : `на ${Math.round(Math.abs(ratio - 1) * 100)}%`;
  return (
    <>
      {worse ? "Да. " : "Нет. "}
      {s.label}: {diff} {worse ? (s.lowerIsBetter ? "выше" : "ниже") : "лучше"}, чем {refName}
      {s.norm !== undefined && s.network !== undefined ? `, при норме ${s.norm.toLocaleString("ru-RU")}${s.unit === "%" ? "%" : ` ${s.unit}`}` : ""}.
    </>
  );
}
