import { Lightbulb, Sparkles } from "lucide-react";

import { useAppContext, useDecideIdea, useFindingIdeas, useMakeFindingIdeas } from "../../api/hooks";
import { AiBadge } from "../../ds/ai";
import { Button, Card, ErrorText } from "../../ds/primitives";

const DECIDED: Record<string, string> = { accepted: "Принята — правило напишем кодом", rejected: "Отклонена" };

/** Patterns the engine has no rule for, proposed by the assistant from aggregates (ADR 0008). */
export function FindingIdeas() {
  const context = useAppContext();
  const ideas = useFindingIdeas();
  const make = useMakeFindingIdeas();
  const decide = useDecideIdea();
  if (!context.data?.assistant) return null;
  const list = ideas.data ?? [];

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Lightbulb size={15} aria-hidden /> Идеи новых находок
        </h2>
        <Button size="sm" variant="ghost" disabled={make.isPending} onClick={() => make.mutate()}>
          <Sparkles size={14} aria-hidden /> {make.isPending ? "Ищу закономерности…" : "Поискать новые"}
        </Button>
      </div>
      {list.length === 0 ? (
        <p className="mt-1 text-sm text-ink-3">
          ИИ просматривает итоги по ресторанам за последние недели и предлагает закономерности, которых нет в правилах.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {list.map((i) => (
            <li key={i.id} className="rounded-[12px] border border-line p-3 text-sm">
              <div className="flex items-center gap-2 font-medium">
                {i.title}
                <AiBadge
                  basis={
                    <>
                      Строки итогов, на которых держится идея:{" "}
                      {i.evidence.map((e) => Object.values(e).filter((v) => typeof v === "string" && !/^a\d+$/.test(v)).join(", ")).join("; ")}
                    </>
                  }
                />
              </div>
              <p className="mt-1 text-ink-2">{i.pattern}</p>
              <p className="mt-1 text-ink-3">Чем грозит: {i.why_it_matters}</p>
              <p className="mt-1 text-ink-3">Как проверять кодом: {i.rule_sketch}</p>
              <div className="mt-2 flex gap-2">
                {DECIDED[i.status] ? (
                  <span className="text-ink-3">{DECIDED[i.status]}</span>
                ) : (
                  <>
                    <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => decide.mutate({ id: i.id, accepted: true })}>
                      Принять
                    </Button>
                    <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => decide.mutate({ id: i.id, accepted: false })}>
                      Отклонить
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <ErrorText error={make.error ?? decide.error} className="mt-2" />
    </Card>
  );
}
