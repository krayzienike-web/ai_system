import { Link } from "@tanstack/react-router";
import { MessageCircle } from "lucide-react";
import { useState } from "react";

import { rubMonth } from "../lib/format";
import { restaurantByCode, processTitle } from "../mock/selectors";
import type { Finding, FindingStatus } from "../mock/types";
import { usePrototype } from "../state/prototype";
import { Button, Card, ConfidenceBadge, Pill } from "./ui";

export const STATUS_LABELS: Record<FindingStatus, string> = {
  new: "Новое",
  in_work: "В работе",
  disputed: "Оспорено",
  in_experiment: "В эксперименте",
  resolved: "Решено",
};

export function useFindingStatus(finding: Finding): FindingStatus {
  const { findingStatus } = usePrototype();
  return findingStatus[finding.id] ?? finding.status;
}

export function EffectValue({ finding, className }: { finding: Finding; className?: string }) {
  if (finding.effectRubMonth === null) {
    return <span className={`text-sm font-medium text-slate-600 ${className ?? ""}`}>Эффект не оценен</span>;
  }
  const loss = finding.kind === "problem";
  return (
    <span className={`font-semibold tabular-nums ${loss ? "text-red-700" : "text-emerald-700"} ${className ?? ""}`}>
      {loss ? "−" : "+"}
      {rubMonth(finding.effectRubMonth)}
    </span>
  );
}

const DISPUTE_REASONS = ["Данные неверные", "Причина другая", "Уже исправлено", "Другое"];

/** Actions a director can take on a finding of their restaurant. */
export function DirectorActions({ finding }: { finding: Finding }) {
  const { takeToWork, dispute, openChat, disputeReasons } = usePrototype();
  const status = useFindingStatus(finding);
  const [disputing, setDisputing] = useState(false);
  const [reason, setReason] = useState(DISPUTE_REASONS[0]!);

  if (disputing) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-label="Причина несогласия"
        >
          {DISPUTE_REASONS.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <Button
          variant="primary"
          onClick={() => {
            dispute(finding.id, reason);
            setDisputing(false);
          }}
        >
          Отправить
        </Button>
        <Button variant="ghost" onClick={() => setDisputing(false)}>
          Отмена
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {status === "new" && (
        <>
          <Button
            variant="primary"
            onClick={() =>
              takeToWork(finding.id, {
                id: `x-${finding.id}`,
                restaurantId: finding.restaurantId ?? "",
                title: finding.actions[0] ?? finding.title,
                source: "Взято директором из сводки",
                findingId: finding.id,
                due: "01.11",
                status: "assigned",
              })
            }
          >
            Беру в работу
          </Button>
          <Button onClick={() => setDisputing(true)}>Не согласен</Button>
        </>
      )}
      {status === "disputed" && (
        <span className="text-sm text-slate-600">Отправлено в УК: «{disputeReasons[finding.id]}»</span>
      )}
      <Button variant="ghost" onClick={() => openChat({ title: finding.title, findingId: finding.id })}>
        <MessageCircle size={14} /> Обсудить с ИИ
      </Button>
    </div>
  );
}

export function FindingCard({ finding, showRestaurant, isDirector }: { finding: Finding; showRestaurant?: boolean; isDirector?: boolean }) {
  const status = useFindingStatus(finding);
  const { openChat } = usePrototype();
  const restaurant = finding.restaurantId ? restaurantByCode(finding.restaurantId) : null;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <Link
          to="/insights/$findingId"
          params={{ findingId: finding.id }}
          className="font-medium text-slate-900 hover:underline"
        >
          {finding.title}
        </Link>
        <EffectValue finding={finding} />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {showRestaurant && <span>{restaurant ? restaurant.name : "Вся сеть"}</span>}
        <span>{processTitle(finding.process)}</span>
        {finding.effectNote && <span>{finding.effectNote}</span>}
        {status !== "new" && <Pill tone={status === "disputed" ? "loss" : "info"}>{STATUS_LABELS[status]}</Pill>}
      </div>
      <div className="mt-3 text-sm text-slate-700">
        <span className="font-medium">
          {finding.metric.label}: {finding.metric.value}
        </span>{" "}
        <span className="text-slate-500">· {finding.metric.benchmark}</span>
        {finding.metric.norm && <span className="text-slate-500"> · {finding.metric.norm}</span>}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        {isDirector ? (
          <DirectorActions finding={finding} />
        ) : (
          <Button variant="ghost" onClick={() => openChat({ title: finding.title, findingId: finding.id })}>
            <MessageCircle size={14} /> Обсудить с ИИ
          </Button>
        )}
        <ConfidenceBadge confidence={finding.confidence} note={finding.confidenceNote} />
      </div>
    </Card>
  );
}
