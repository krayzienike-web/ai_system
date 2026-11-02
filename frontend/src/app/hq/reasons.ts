// Why a finding is rejected: the review form and the assistant's draft verdict use the same words.
import type { RejectReason } from "../../api/types";

export const REASONS: { reason: RejectReason; title: string; hint: string }[] = [
  {
    reason: "data",
    title: "Ошибка в данных",
    hint: "файл неполный, не та инвентаризация, перепутаны единицы",
  },
  {
    reason: "logic",
    title: "Ошибка в логике расчета",
    hint: "формула или правило не подходят — опишите, что не так",
  },
  {
    reason: "false_alarm",
    title: "Не проблема",
    hint: "цифры верны, но это известно, согласовано или сезонно",
  },
  { reason: "other", title: "Другое", hint: "опишите" },
];
export const REASON_TITLE = Object.fromEntries(
  REASONS.map((r) => [r.reason, r.title]),
) as Record<RejectReason, string>;
