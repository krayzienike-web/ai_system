// Demo mode: the review of engine findings on a snapshot taken from the real engine on the demo network
// (backend: `load-demo`, then the verification of each finding). Verdicts live in the browser.
import { ApiError } from "./client";
import snapshot from "./demoReview.json";
import type { ApiFinding, ReviewStatus, Verification } from "./types";

const items = (
  snapshot as unknown as { finding: ApiFinding; verification: Verification }[]
).map((x) => ({
  finding: { ...x.finding },
  verification: x.verification,
}));
const today = () => new Date().toISOString().slice(0, 10);

export function demoReview(
  path: string,
  init: RequestInit,
  isHq: boolean,
  isAdmin: boolean,
): unknown {
  if (!isHq) throw new ApiError(403, "Находки проверяет управляющая компания");
  const list = /^\/findings\?review=(pending|confirmed|rejected)$/.exec(path);
  if (list)
    return items
      .filter((x) => x.finding.review_status === (list[1] as ReviewStatus))
      .map((x) => x.finding);
  if (path === "/analytics/run") {
    if (!isAdmin) throw new ApiError(403, "Пересчет запускает администратор");
    return {
      created: 0,
      updated: items.length,
      removed: 0,
      drafts: items.length,
    };
  }
  const m = /^\/findings\/([^/]+)\/(verification|review)$/.exec(path);
  const item = m && items.find((x) => x.finding.id === m[1]);
  if (!m || !item) throw new ApiError(404, "Находка не найдена");
  if (m[2] === "verification") return item.verification;
  const body = JSON.parse(String(init.body)) as {
    verdict: string;
    reason?: ApiFinding["review_reason"];
    note?: string;
  };
  if (body.verdict === "reject" && !body.reason)
    throw new ApiError(
      422,
      "Укажите, что не так: данные, логика расчета или это не проблема",
    );
  if (
    body.verdict === "reject" &&
    (body.reason === "logic" || body.reason === "other") &&
    !body.note?.trim()
  )
    throw new ApiError(
      422,
      "Опишите, что не так, — по этому описанию поправим движок",
    );
  const f = item.finding;
  f.review_status =
    body.verdict === "confirm"
      ? "confirmed"
      : body.verdict === "reject"
        ? "rejected"
        : "pending";
  f.review_reason = body.verdict === "reject" ? (body.reason ?? null) : null;
  f.review_note = body.note?.trim() || null;
  f.reviewed_on = body.verdict === "reopen" ? null : today();
  return f;
}
