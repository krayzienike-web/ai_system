import { Eye, Sparkles } from "lucide-react";

import { useAppContext, useMakePrecheck, usePrecheck, usePrecheckStats } from "../../api/hooks";
import { AiBadge } from "../../ds/ai";
import { Button, Card, ErrorText } from "../../ds/primitives";

const VERDICT: Record<string, string> = {
  confirm: "Подтвердить",
  reject: "Отклонить",
  look_closer: "Посмотреть внимательнее",
};
const REASON: Record<string, string> = {
  data: "данные неверны или неполные",
  logic: "правило не подходит к этому случаю",
  false_alarm: "цифры верны, но это не проблема",
  other: "другое",
};

/** Before the verdict: what the code says to look at, and the assistant's draft verdict (ADR 0008). */
export function PrecheckPanel({ findingId }: { findingId: string }) {
  const context = useAppContext();
  const pre = usePrecheck(findingId);
  const make = useMakePrecheck(findingId);
  if (!pre.data) return null;
  const { flags, draft } = pre.data;
  const assistant = context.data?.assistant ?? false;

  return (
    <Card className="p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Eye size={15} aria-hidden /> На что посмотреть
      </h2>
      {flags.length === 0 ? (
        <p className="mt-1 text-sm text-ink-3">Система не нашла, что могло бы объяснить отклонение без проблемы.</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-sm">
          {flags.map((f) => (
            <li key={f.code}>
              <span className="font-medium">{f.title}</span>
              <span className="block text-xs text-ink-3">{f.note}</span>
            </li>
          ))}
        </ul>
      )}

      {draft && (
        <div className="mt-4 rounded-[12px] bg-paper/60 p-3 text-sm" aria-label="Черновик вердикта ИИ">
          <div className="flex items-center gap-2 font-semibold">
            Черновик ИИ: {VERDICT[draft.verdict] ?? draft.verdict}
            {draft.reason && <span className="font-normal text-ink-3">— {REASON[draft.reason] ?? draft.reason}</span>}
            <AiBadge basis="Черновик по фактам находки и флагам выше. Вердикт ставите вы." />
          </div>
          <p className="mt-1 text-ink-2">{draft.rationale}</p>
          {draft.look_at.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-ink-3">
              {draft.look_at.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {assistant && (
        <Button className="mt-3" size="sm" variant={draft ? "ghost" : "secondary"} disabled={make.isPending} onClick={() => make.mutate()}>
          <Sparkles size={14} aria-hidden /> {make.isPending ? "Готовлю черновик…" : draft ? "Черновик заново" : "Черновик вердикта от ИИ"}
        </Button>
      )}
      <ErrorText error={make.error} className="mt-2" />
    </Card>
  );
}

/** «ИИ предлагал / человек решил»: how often the assistant's draft matched the analyst's verdict. */
export function PrecheckStatsLine() {
  const stats = usePrecheckStats().data;
  if (!stats || stats.decided === 0) return null;
  return (
    <p className="text-sm text-ink-3">
      Черновики ИИ совпали с вашим вердиктом в {stats.agreed} из {stats.decided} проверенных находок.
    </p>
  );
}
