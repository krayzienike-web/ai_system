import { Link, useParams } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  FileText,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  useRestaurants,
  useReviewFinding,
  useReviewFindings,
  useRunAnalytics,
  useVerification,
} from "../../api/hooks";
import type {
  ApiFinding,
  RejectReason,
  ReviewStatus,
  VerificationStep,
} from "../../api/types";
import {
  Button,
  Card,
  cx,
  EmptyState,
  PageTitle,
  Pill,
  Skeleton,
} from "../../ds/primitives";
import { MODULE_TITLE, perMonth, plural } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";
import { RecalcNote } from "../analytics/RecalcNote";
import { ReviewTrace } from "../findings/ReviewTrace";

const TABS: { status: ReviewStatus; title: string }[] = [
  { status: "pending", title: "На проверке" },
  { status: "confirmed", title: "Подтверждены" },
  { status: "rejected", title: "Отклонены" },
];

const REASONS: { reason: RejectReason; title: string; hint: string }[] = [
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
const REASON_TITLE = Object.fromEntries(
  REASONS.map((r) => [r.reason, r.title]),
) as Record<RejectReason, string>;


/** "617.65" → "617,65", "2026-08-04" → "04.08.2026": numbers and dates as people read them. */
const ru = (v: unknown): string => {
  if (v === true) return "да";
  if (v === false) return "нет";
  if (v == null) return "—";
  const t = String(v);
  if (/^-?\d+\.\d+$/.test(t)) return t.replace(".", ",");
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  return d ? `${d[3]}.${d[2]}.${d[1]}` : t;
};

const dateRu = (iso: string | null | undefined) =>
  iso
    ? new Date(`${iso}T00:00:00`)
        .toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
        .replace(".", "")
    : "";

function useRestaurantName() {
  const restaurants = useRestaurants();
  return (id: string | null) =>
    id
      ? (restaurants.data?.find((r) => r.id === id)?.name ?? "Ресторан")
      : "Вся сеть";
}

/** How many engine findings wait for a check (HQ only): the menu badge. */
export function useReviewCount(enabled: boolean) {
  return useReviewFindings("pending", enabled).data?.length ?? 0;
}

export function ReviewPage() {
  const viewer = useViewer();
  const [tab, setTab] = useState<ReviewStatus>("pending");
  const list = useReviewFindings(tab);
  const run = useRunAnalytics();
  const { notify } = useUi();
  const name = useRestaurantName();

  return (
    <div className="mx-auto max-w-[920px] space-y-5">
      <PageTitle
        title="Проверка находок"
        subtitle="Пока движок новый, каждую находку сверяем с загруженными данными. Директор видит только подтвержденные"
        actions={
          viewer?.isAdmin && (
            <Button
              onClick={() =>
                run.mutate(undefined, {
                  onSuccess: (r) =>
                    notify(
                      r.status === "done"
                        ? `Пересчитано: ${r.created ?? 0} ${plural(r.created ?? 0, ["новая", "новые", "новых"])}, ${r.updated ?? 0} обновлено`
                        : "Пересчет запущен: находки обновятся, как только он закончится",
                    ),
                })
              }
              disabled={run.isPending}
            >
              <RefreshCw
                size={15}
                className={run.isPending ? "animate-spin" : ""}
              />{" "}
              Пересчитать находки
            </Button>
          )
        }
      />
      <RecalcNote />
      <div role="tablist" className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.status}
            role="tab"
            aria-selected={tab === t.status}
            onClick={() => setTab(t.status)}
            className={cx(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              tab === t.status
                ? "border-brand text-brand-strong"
                : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {t.title}
          </button>
        ))}
      </div>
      {list.isLoading ? (
        <Skeleton className="h-40" />
      ) : !list.data?.length ? (
        <EmptyState
          title={
            tab === "pending" ? "Все находки проверены" : "Здесь пока пусто"
          }
        >
          {tab === "pending"
            ? "Новые появятся после загрузки данных и пересчета."
            : null}
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {list.data.map((f) => (
            <li key={f.id}>
              <Link
                to="/review/$findingId"
                params={{ findingId: f.id }}
                className="block rounded-[16px] border border-line bg-surface p-4 transition-colors hover:border-brand"
              >
                <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
                  <span className="font-semibold text-ink-2">
                    {name(f.restaurant_id)}
                  </span>
                  <span>·</span>
                  <span>
                    {f.module} · {MODULE_TITLE[f.module ?? ""] ?? ""}
                  </span>
                  {f.period_from && (
                    <span>
                      · {dateRu(f.period_from)} – {dateRu(f.period_to)}
                    </span>
                  )}
                  {f.review_reason && (
                    <Pill tone="loss">{REASON_TITLE[f.review_reason]}</Pill>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-semibold">{f.title}</span>
                  <span className="num font-semibold text-loss">
                    {f.effect_rub_month ? (
                      perMonth(Number(f.effect_rub_month))
                    ) : (
                      <span className="text-sm font-normal text-ink-3">
                        {f.effect_note}
                      </span>
                    )}
                  </span>
                </div>
                {f.headline && (
                  <p className="mt-1 text-sm text-ink-2">{f.headline}</p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SourceRows({ step }: { step: VerificationStep }) {
  const [open, setOpen] = useState(false);
  if (!step.rows.length) return null;
  const columns = Object.keys(step.rows[0]!);
  const TITLES: Record<string, string> = {
    day: "Дата",
    doc: "Документ",
    supplier: "Поставщик",
    product: "Товар",
    cost: "Стоимость, ₽",
    price_before: "Цена квартал назад, ₽",
    cost_before: "Стоимость тогда, ₽",
    qty: "Кол-во",
    amount: "Сумма, ₽",
    price: "Цена, ₽",
    book: "По учету",
    actual: "Факт",
    reason: "Причина",
    file: "Файл",
    dish: "Блюдо",
    portions: "Порций",
    per_portion: "На порцию",
    usage: "Расход",
    restaurant: "Ресторан",
    share: "Сверх техкарты",
    over: "Выше допуска",
    contract: "По договору, ₽",
    overpay: "Переплата, ₽",
  };
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 text-xs font-medium text-brand-strong hover:underline"
      >
        <ChevronDown
          size={14}
          className={cx("transition-transform", open && "rotate-180")}
        />
        {open ? "Скрыть строки" : `Исходные строки: ${step.rows.length}`}
      </button>
      {open && (
        <div className="mt-2 max-h-80 overflow-auto rounded-[10px] border border-line">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-paper text-left text-ink-3">
              <tr>
                {columns.map((c) => (
                  <th key={c} className="px-2 py-1.5 font-medium">
                    {TITLES[c] ?? c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="num">
              {step.rows.map((r, i) => (
                <tr key={i} className="border-t border-line">
                  {columns.map((c) => (
                    <td key={c} className="px-2 py-1.5 whitespace-nowrap">
                      {ru(r[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function VerdictForm({ f }: { f: ApiFinding }) {
  const viewer = useViewer();
  const review = useReviewFinding();
  const { notify } = useUi();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState<RejectReason | null>(null);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState(false);
  if (!viewer?.isHq) return null;
  const send = (verdict: "confirm" | "reject" | "reopen") => {
    // The server asks the same: a logic error or «other» needs a description to fix the engine by.
    const needsNote = verdict === "reject" && (reason === "logic" || reason === "other");
    setNoteError(needsNote && !note.trim());
    if (needsNote && !note.trim()) return;
    review.mutate(
      {
        id: f.id,
        verdict,
        ...(verdict === "reject"
          ? { reason: reason ?? undefined, note }
          : { note }),
      },
      {
        onSuccess: () => {
          setRejecting(false);
          notify(
            verdict === "confirm"
              ? "Подтверждено: директор увидит находку"
              : verdict === "reject"
                ? "Отклонено, причина сохранена"
                : "Возвращено на проверку",
          );
        },
      },
    );
  };

  return (
    <Card className="space-y-3 p-4">
      {f.review_status !== "pending" ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm">
            {f.review_status === "confirmed" ? (
              <span className="inline-flex items-center gap-1.5 font-medium text-gain">
                <CheckCircle2 size={16} /> Подтверждено {dateRu(f.reviewed_on)}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 font-medium text-loss">
                <XCircle size={16} /> Отклонено {dateRu(f.reviewed_on)}:{" "}
                {f.review_reason && REASON_TITLE[f.review_reason]}
              </span>
            )}
            {f.review_note && (
              <span className="mt-1 block text-ink-2">«{f.review_note}»</span>
            )}
          </span>
          <Button
            size="sm"
            onClick={() => send("reopen")}
            disabled={review.isPending}
          >
            <RotateCcw size={14} /> Вернуть на проверку
          </Button>
        </div>
      ) : rejecting ? (
        <div className="space-y-3">
          <div className="text-sm font-medium">Что не так?</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {REASONS.map((r) => (
              <label
                key={r.reason}
                className={cx(
                  "cursor-pointer rounded-[12px] border p-3 text-sm",
                  reason === r.reason
                    ? "border-brand bg-brand-soft"
                    : "border-line",
                )}
              >
                <input
                  type="radio"
                  name="reason"
                  className="sr-only"
                  checked={reason === r.reason}
                  onChange={() => setReason(r.reason)}
                />
                <span className="font-medium">{r.title}</span>
                <span className="block text-xs text-ink-3">{r.hint}</span>
              </label>
            ))}
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="Комментарий"
            placeholder="Что именно не так — по этому описанию поправим данные или логику движка"
            className="min-h-20 w-full rounded-[10px] border border-line-strong bg-surface p-2.5 text-sm outline-none focus:border-brand"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              onClick={() => send("reject")}
              disabled={!reason || review.isPending}
            >
              Отклонить
            </Button>
            <Button onClick={() => setRejecting(false)}>Отмена</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            onClick={() => send("confirm")}
            disabled={review.isPending}
          >
            <CheckCircle2 size={15} /> Подтвердить — показать директору
          </Button>
          <Button onClick={() => setRejecting(true)}>
            <XCircle size={15} /> Отклонить
          </Button>
        </div>
      )}
      {noteError && (
        <p className="text-sm text-loss">
          Опишите, что не так, — по этому описанию поправим движок
        </p>
      )}
      {review.isError && !noteError && (
        <p className="text-sm text-loss">
          {review.error instanceof ApiError
            ? review.error.message
            : "Не получилось сохранить"}
        </p>
      )}
    </Card>
  );
}

export function ReviewFindingPage() {
  const { findingId } = useParams({ from: "/app/review/$findingId" });
  const all = [
    useReviewFindings("pending"),
    useReviewFindings("confirmed"),
    useReviewFindings("rejected"),
  ];
  const f = all.flatMap((q) => q.data ?? []).find((x) => x.id === findingId);
  const v = useVerification(findingId);
  const name = useRestaurantName();

  if (all.some((q) => q.isError) || v.isError || (!f && all.every((q) => q.isSuccess)))
    return (
      <div className="mx-auto max-w-[920px] space-y-5">
        <Link to="/review" className="text-sm text-brand-strong hover:underline">
          ← Все находки на проверке
        </Link>
        <EmptyState title="Находка не найдена">
          Возможно, после пересчета ее больше нет в данных или ссылка устарела.
        </EmptyState>
      </div>
    );
  if (!f || v.isLoading)
    return <Skeleton className="mx-auto h-96 max-w-[920px]" />;
  const data = v.data;
  const failed = data?.checks?.filter((c) => !c.ok) ?? [];

  return (
    <div className="mx-auto max-w-[920px] space-y-5">
      <Link to="/review" className="text-sm text-brand-strong hover:underline">
        ← Все находки на проверке
      </Link>
      <PageTitle
        title={f.title}
        subtitle={`${name(f.restaurant_id)} · ${f.module} ${MODULE_TITLE[f.module ?? ""] ?? ""}${f.period_from ? ` · ${dateRu(f.period_from)} – ${dateRu(f.period_to)}` : ""}`}
      />
      {f.headline && <p className="text-ink-2">{f.headline}</p>}
      <Card className="flex flex-wrap items-end justify-between gap-3 p-4">
        <ReviewTrace f={f} />
        {f.review_status === "confirmed" && (
          <Link to="/findings" className="text-sm font-medium text-brand-strong hover:underline">
            Открыть в находках →
          </Link>
        )}
      </Card>
      <VerdictForm f={f} />

      {!data?.supported ? (
        <Card className="p-4 text-sm text-ink-2">
          {data?.note ?? "Расчет по шагам недоступен"}
        </Card>
      ) : (
        <>
          {data.checks && data.checks.length > 0 && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold">
                Сверка с загруженными данными
              </h2>
              {failed.length > 0 && (
                <p className="mt-1 flex items-center gap-1.5 text-sm text-warn">
                  <AlertTriangle size={15} /> {failed.length}{" "}
                  {plural(failed.length, [
                    "проверка не прошла",
                    "проверки не прошли",
                    "проверок не прошли",
                  ])}{" "}
                  — посмотрите, прежде чем подтверждать
                </p>
              )}
              <ul className="mt-2 space-y-1.5 text-sm">
                {data.checks.map((c) => (
                  <li key={c.check} className="flex gap-2">
                    {c.ok ? (
                      <CheckCircle2
                        size={16}
                        className="mt-0.5 shrink-0 text-gain"
                      />
                    ) : (
                      <XCircle
                        size={16}
                        className="mt-0.5 shrink-0 text-loss"
                      />
                    )}
                    <span>
                      {c.check}
                      {c.note && (
                        <span className="block text-xs text-ink-3">
                          {c.note}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="p-4">
            <h2 className="text-sm font-semibold">Расчет по шагам</h2>
            {data.formula && (
              <p className="mt-1 rounded-[10px] bg-paper px-3 py-2 font-mono text-xs text-ink-2">
                {data.formula}
              </p>
            )}
            <ol className="mt-3 space-y-3">
              {data.steps?.map((s) => (
                <li
                  key={s.id}
                  className="border-t border-line pt-3 first:border-0 first:pt-0"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                    <span className="inline-flex items-center gap-1.5">
                      <FileText size={14} className="text-ink-3" /> {s.label}
                    </span>
                    {s.value !== null && (
                      <span className="num font-semibold">
                        {ru(s.value)} {s.unit}
                      </span>
                    )}
                  </div>
                  <div className="mt-1">
                    <SourceRows step={s} />
                  </div>
                </li>
              ))}
            </ol>
            {data.result && data.result.length > 0 && (
              <dl className="mt-4 space-y-1.5 rounded-[12px] bg-brand-soft p-3 text-sm">
                {data.result.map((r) => (
                  <div
                    key={r.label}
                    className="flex flex-wrap justify-between gap-2"
                  >
                    <dt>{r.label}</dt>
                    <dd className="num font-semibold">
                      {ru(r.value)} {r.unit}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </Card>

          {data.rules && data.rules.length > 0 && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold">
                Почему это находка: сработавшие правила
              </h2>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-ink-3">
                    <tr>
                      <th className="py-1 font-medium">Правило</th>
                      <th className="py-1 text-right font-medium">Значение</th>
                      <th className="py-1 text-right font-medium">Порог</th>
                      <th className="py-1" />
                    </tr>
                  </thead>
                  <tbody className="num">
                    {data.rules.map((r) => (
                      <tr key={r.rule} className="border-t border-line">
                        <td className="py-1.5 pr-3 font-sans">{r.rule}</td>
                        <td className="py-1.5 text-right">{r.value}</td>
                        <td className="py-1.5 text-right text-ink-3">
                          {r.threshold}
                        </td>
                        <td className="py-1.5 pl-2 text-right">
                          {r.passed ? (
                            <CheckCircle2
                              size={15}
                              className="inline text-gain"
                            />
                          ) : (
                            <XCircle size={15} className="inline text-ink-3" />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {data.history && data.history.length > 1 && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold">
                По периодам между инвентаризациями
              </h2>
              <div className="mt-2 overflow-x-auto">
                <table className="num w-full text-sm">
                  <thead className="text-left text-xs text-ink-3">
                    <tr>
                      <th className="py-1 font-medium">Период</th>
                      <th className="py-1 text-right font-medium">
                        По техкартам
                      </th>
                      <th className="py-1 text-right font-medium">Факт</th>
                      <th className="py-1 text-right font-medium">Списания</th>
                      <th className="py-1 text-right font-medium">
                        Сверх техкарты
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.history.map((h) => (
                      <tr key={h.to} className="border-t border-line">
                        <td className="py-1.5">
                          {dateRu(h.from)} – {dateRu(h.to)}
                        </td>
                        <td className="py-1.5 text-right">{ru(h.theory)}</td>
                        <td className="py-1.5 text-right">{ru(h.actual)}</td>
                        <td className="py-1.5 text-right">{ru(h.write_off)}</td>
                        <td className="py-1.5 text-right font-semibold">
                          {(Number(h.share) * 100).toFixed(1).replace(".", ",")}
                          %
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {data.interpretation && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold">Как это читать</h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                {data.interpretation.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
