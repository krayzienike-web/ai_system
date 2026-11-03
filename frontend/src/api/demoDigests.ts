// The prototype's weekly digests (stage 6): the recorded digests, with what the visitor did on them —
// «Беру в работу» (a task: the item is «в работе») and «Не согласен» (kept for the session, shown to the HQ).
// «Пересобрать» answers the recorded digest: the prototype's data do not change.
import { ApiError } from "./client";
import type { Digest, DigestItem, Disagreement, DisagreeReason } from "./types";

interface Mark {
  reason: string;
  comment: string | null;
  restaurant: string;
  title: string;
  at: string;
}
/** finding id → the director's «Не согласен» (one director per demo restaurant: the key needs no user). */
const marks = new Map<string, Mark>();

export function demoDisagree(
  findingId: string,
  method: string,
  body: Record<string, unknown>,
  who: { hq: boolean; restaurant: string | null },
  item: DigestItem | undefined,
): undefined {
  if (who.hq || !who.restaurant) throw new ApiError(403, "«Не согласен» — для директора ресторана");
  if (!item) throw new ApiError(404, "Находка не найдена");
  if (method === "DELETE") {
    if (!marks.delete(findingId)) throw new ApiError(404, "Вы не отмечали несогласие с этим пунктом");
    return undefined;
  }
  const reason = String(body.reason ?? "");
  const comment = typeof body.comment === "string" && body.comment.trim() ? body.comment.trim() : null;
  if (!["wrong_data", "explained", "already_fixed", "other"].includes(reason)) throw new ApiError(422, "Неизвестная причина");
  if (reason === "other" && !comment) throw new ApiError(422, "Напишите, с чем не согласны");
  marks.set(findingId, { reason, comment, restaurant: who.restaurant, title: item.title, at: new Date().toISOString() });
  return undefined;
}

/** A recorded digest as the visitor sees it now. */
export function demoDigest(d: Digest, taken: (findingId: string) => boolean, director: boolean): Digest {
  const mark = (i: DigestItem): DigestItem => ({
    ...i,
    taken: i.taken || taken(i.finding_id),
    disagreed: director ? (marks.get(i.finding_id)?.reason ?? null) : null,
    disagreed_comment: director ? (marks.get(i.finding_id)?.comment ?? null) : null,
  });
  return { ...d, problems: d.problems.map(mark), opportunities: d.opportunities.map(mark), risks: d.risks.map(mark) };
}

/** The HQ's list, of one restaurant when `restaurant` (its «R01 · Название» label) is given. */
export function demoDisagreements(
  recorded: Disagreement[],
  reasons: DisagreeReason[],
  restaurant?: string,
): Disagreement[] {
  const title = (r: string) => reasons.find((x) => x.reason === r)?.title ?? r;
  const added = [...marks.entries()].map(([findingId, m], n) => ({
    id: `demo-disagreement-${n}`,
    finding_id: findingId,
    finding_title: m.title,
    restaurant: m.restaurant,
    reason: m.reason,
    reason_title: title(m.reason),
    comment: m.comment,
    created_at: m.at,
  }));
  const all = [...added.reverse(), ...recorded];
  return restaurant ? all.filter((d) => d.restaurant === restaurant) : all;
}

/** Every digest item of the recordings, by finding id: what «Не согласен» may name. */
export function digestItems(answers: Record<string, unknown>[]): Map<string, DigestItem> {
  const out = new Map<string, DigestItem>();
  for (const a of answers)
    for (const [path, value] of Object.entries(a))
      if (path.startsWith("/digests/latest")) {
        const d = value as Digest;
        for (const i of [...d.problems, ...d.opportunities, ...d.risks]) out.set(i.finding_id, i);
      }
  return out;
}
