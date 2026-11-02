import { Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";

import { useDecideSuggestion, useHypotheses, useMakeHypotheses } from "../../api/hooks";
import type { Hypotheses } from "../../api/types";
import { AiBadge } from "../../ds/ai";
import { Button, ErrorText, Pill } from "../../ds/primitives";
import { useViewer } from "../../lib/useViewer";

const LIKELIHOOD_TONE = { высокая: "loss", средняя: "neutral", низкая: "neutral" } as const;
// A decision is shared by everyone who sees the finding: say whose it is (review 02.11, front p. 3).
const VERDICT: Record<string, string> = { accepted: "полезно", rejected: "не то" };
const decided = (h: Hypotheses) =>
  VERDICT[h.status] ? `${h.decided_by_me ? "Вы отметили" : "Отмечено"}: ${VERDICT[h.status]}` : null;

/** What the proposal was made from, in the server's words (ADR 0008, «рядом видно, на чем основано»). */
function Basis({ h }: { h: Hypotheses }) {
  return <>Предположения по фактам, которые собрала система: {h.basis_words.join(", ")}. Проверьте на месте.</>;
}

/** «Почему так» from the assistant: likely causes and how to check them, steps that respect the network's rules. */
export function AiHypotheses({ findingId }: { findingId: string }) {
  const viewer = useViewer();
  const current = useHypotheses(findingId, true);
  const make = useMakeHypotheses(findingId);
  // After «Разобрать с ИИ» the button is gone: focus moves to the result (review 02.11, front p. 9).
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (make.isSuccess) titleRef.current?.focus();
  }, [make.isSuccess]);
  const decide = useDecideSuggestion(findingId);
  const h = current.data;
  const canAsk = viewer?.can("ai.chat") ?? false;
  // The button waits for the answer: a proposal may already be there (review 02.11, front p. 4).
  if (current.isPending) return null;
  if (current.isError) return <ErrorText error={current.error} className="mt-5" />;

  if (!h) {
    if (!canAsk) return null;
    return (
      <div className="mt-5 rounded-[16px] border border-dashed border-line-strong p-4">
        <div className="text-sm text-ink-2">ИИ разберет эту находку по вашим данным: что менялось у поставщиков, в списаниях и инвентаризациях.</div>
        <Button className="mt-3" size="sm" variant="primary" disabled={make.isPending} onClick={() => make.mutate()}>
          <Sparkles size={14} aria-hidden /> {make.isPending ? "Разбираю…" : "Разобрать с ИИ"}
        </Button>
        <ErrorText error={make.error} className="mt-2" />
      </div>
    );
  }

  return (
    <section aria-labelledby={`hyp-${findingId}`} className="mt-5 rounded-[16px] border border-line bg-paper/50 p-4">
      <h3 id={`hyp-${findingId}`} ref={titleRef} tabIndex={-1} className="mb-3 flex items-center gap-2 text-sm font-semibold outline-none">
        Версии ИИ <AiBadge basis={<Basis h={h} />} />
      </h3>
      <ol className="space-y-3">
        {h.hypotheses.map((x) => (
          <li key={x.cause} className="text-sm">
            <div className="flex flex-wrap items-center gap-2 font-medium">
              {x.cause_title}
              <Pill tone={LIKELIHOOD_TONE[x.likelihood as keyof typeof LIKELIHOOD_TONE] ?? "neutral"}>вероятность {x.likelihood}</Pill>
            </div>
            <div className="mt-1 text-ink-2">{x.why}</div>
            <div className="mt-1 text-ink-3">Как проверить: {x.check}</div>
          </li>
        ))}
      </ol>
      {h.steps.length > 0 && (
        <div className="mt-4 text-sm">
          <div className="font-medium">Что сделать</div>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-2">
            {h.steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          {h.rules_note && <p className="mt-2 text-xs text-ink-3">{h.rules_note}</p>}
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        {decided(h) ? (
          <span className="text-ink-3">{decided(h)}</span>
        ) : (
          <>
            <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => decide.mutate({ id: h.id, accepted: true })}>
              Полезно
            </Button>
            <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => decide.mutate({ id: h.id, accepted: false })}>
              Не то
            </Button>
          </>
        )}
        {canAsk && (
          <Button size="sm" variant="ghost" disabled={make.isPending} onClick={() => make.mutate()}>
            {make.isPending ? "Разбираю…" : "Разобрать заново"}
          </Button>
        )}
      </div>
      <ErrorText error={make.error ?? decide.error} className="mt-2" />
    </section>
  );
}
