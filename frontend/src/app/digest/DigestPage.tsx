import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { CheckCircle2, MessageCircle, RefreshCw, ThumbsDown } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import {
  useDigest,
  useDigestWeeks,
  useDisagree,
  useDisagreeReasons,
  useDisagreements,
  useRebuildDigest,
  useRestaurants,
} from "../../api/hooks";
import type { Digest, DigestItem } from "../../api/types";
import { Button, Card, cx, Dialog, EmptyState, ErrorText, PageTitle, Pill, Reveal, Skeleton, type Tone } from "../../ds/primitives";
import { PROCESS_ICON } from "../../ds/viz";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";
import { TakeToWorkDialog } from "../findings/parts";

const STATUS: Record<string, { tone: Tone; word: string }> = {
  good: { tone: "gain", word: "Норма" },
  warning: { tone: "warn", word: "Внимание" },
  critical: { tone: "loss", word: "Проблема" },
};

const dmy = (iso: string) => iso.split("-").reverse().join(".");

/** «Сводка недели» (docs/08 part 1): what the code computed for the week, in the model's or the rules' words.
 * A director reads their restaurant's; the HQ picks the network or a restaurant. Every figure is the server's. */
export function DigestPage() {
  const viewer = useViewer();
  const search = useSearch({ from: "/app/digest" });
  const navigate = useNavigate({ from: "/digest" });
  const restaurant = viewer?.isHq ? search.restaurant : undefined;
  const digest = useDigest(restaurant, search.week);
  const weeks = useDigestWeeks(restaurant);
  const restaurants = useRestaurants();
  const rebuild = useRebuildDigest();
  const { notify } = useUi();
  if (!viewer) return null;

  const missing = digest.error instanceof ApiError && digest.error.status === 404;
  const d = digest.data;

  return (
    <div className="space-y-6">
      <PageTitle
        title={d ? (d.scope === "network" ? "Сводка сети" : `Сводка · ${d.restaurant}`) : "Сводка недели"}
        subtitle={
          d && (
            <>
              Неделя {d.week}
              {d.scope === "network" && d.restaurants_count ? ` · ресторанов: ${d.restaurants_count}` : ""}
            </>
          )
        }
        actions={
          <>
            {viewer.isHq && (
              <select
                aria-label="Чья сводка"
                className="rounded-full border border-line-strong bg-surface px-3 py-2 text-sm"
                value={restaurant ?? ""}
                onChange={(e) => void navigate({ search: { restaurant: e.target.value || undefined } })}
              >
                <option value="">Вся сеть</option>
                {(restaurants.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.code} · {r.name}
                  </option>
                ))}
              </select>
            )}
            {(weeks.data?.length ?? 0) > 1 && (
              <select
                aria-label="Неделя"
                className="rounded-full border border-line-strong bg-surface px-3 py-2 text-sm"
                value={search.week ?? ""}
                onChange={(e) => void navigate({ search: (s) => ({ ...s, week: e.target.value || undefined }) })}
              >
                <option value="">Последняя</option>
                {weeks.data!.map((w) => (
                  <option key={w.week_start} value={w.week_start}>
                    {dmy(w.week_start)}–{dmy(w.week_end)}
                  </option>
                ))}
              </select>
            )}
            <Button
              variant="ghost"
              disabled={rebuild.isPending}
              onClick={() =>
                rebuild.mutate(restaurant, {
                  onSuccess: () => {
                    notify("Сводка пересобрана по текущим находкам");
                    void navigate({ search: (s) => ({ ...s, week: undefined }) });
                  },
                })
              }
            >
              <RefreshCw size={15} className={cx(rebuild.isPending && "animate-spin")} /> Пересобрать
            </Button>
          </>
        }
      />
      {rebuild.isError && <ErrorText error={rebuild.error} fallback="Не получилось пересобрать сводку" />}
      {digest.isPending && <Skeleton className="h-[520px]" />}
      {missing && (
        <EmptyState title="Сводки пока нет">
          Сводка выходит по понедельникам о прошлой неделе. Ее можно собрать и сейчас — кнопкой «Пересобрать».
        </EmptyState>
      )}
      {digest.isError && !missing && <ErrorText error={digest.error} fallback="Не получилось загрузить сводку" />}
      {d && <DigestView d={d} canReact={!viewer.isHq && !search.week} />}
      {viewer.can("network.compare") && <Disagreements />}
    </div>
  );
}

function DigestView({ d, canReact }: { d: Digest; canReact: boolean }) {
  return (
    <>
      <Reveal>
        <section className="grid gap-6 rounded-[24px] bg-ink p-6 text-white sm:p-8 lg:grid-cols-[1fr_1.3fr]">
          <div>
            <div className="text-sm text-spark">На столе в месяц</div>
            <div className="mt-1 font-display text-[44px] leading-none font-semibold tracking-tight">{d.on_table.total ?? "0 ₽"}</div>
            <div className="mt-3 space-y-1 text-sm text-white/80">
              <div>Потери: {d.on_table.losses ?? "—"}</div>
              <div>Потенциал: {d.on_table.potential ?? "—"}</div>
            </div>
          </div>
          <div className="rounded-[18px] bg-white/[0.06] p-5">
            <div className="text-sm font-medium">Главное за неделю</div>
            <p className="mt-3 text-[15px] leading-relaxed text-white/90">{d.headline}</p>
            <div className="mt-3 text-xs text-white/50">
              {d.source === "model"
                ? "Текст написал ИИ, каждое число сверено с расчетом"
                : "Текст собран по правилам из расчета"}
            </div>
          </div>
        </section>
      </Reveal>

      <Kpis d={d} />

      <section aria-labelledby="processes">
        <h2 id="processes" className="mb-3 font-display text-lg font-semibold">Карта процессов</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {d.processes.map((p) => {
            const Icon = PROCESS_ICON[p.process as keyof typeof PROCESS_ICON];
            const s = STATUS[p.status] ?? STATUS.warning!;
            return (
              <Card key={p.process} className="p-3 sm:p-4">
                <div className="flex items-center gap-2 text-sm font-medium">
                  {Icon && <Icon size={16} className="text-ink-3" />} {p.title}
                </div>
                <div className="mt-3 flex items-baseline gap-2">
                  <span className="num font-display text-2xl font-semibold">{p.index}</span>
                  <span className="text-xs text-ink-3">из 100</span>
                  {p.change !== null && p.change !== 0 && (
                    <span className={cx("num text-xs", p.change > 0 ? "text-gain" : "text-loss")}>
                      {p.change > 0 ? `+${p.change}` : p.change} к прошлой
                    </span>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Pill tone={s.tone}>{s.word}</Pill>
                  {p.losses_per_month && <span className="text-xs text-ink-3">{p.losses_per_month} в месяц</span>}
                </div>
              </Card>
            );
          })}
        </div>
      </section>

      <Items title="Где теряем деньги" empty="Открытых проблем с оценкой в рублях нет" items={d.problems} digest={d} canReact={canReact} />
      <Items title="Что улучшить" empty="Новых возможностей нет" items={d.opportunities} digest={d} canReact={canReact} />
      {d.risks.length > 0 && <Items title="Риски на ближайшие дни" empty="" items={d.risks} digest={d} canReact={canReact} />}

      <section aria-labelledby="improved" className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 id="improved" className="font-display text-lg font-semibold">Что улучшилось</h2>
          <ul className="mt-3 space-y-1.5 text-sm text-ink-2">
            <li>Выполнено задач за неделю: {d.improved.tasks_done}</li>
            {d.improved.tasks.map((t) => (
              <li key={t} className="flex gap-2">
                <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-gain-icon" /> {t}
              </li>
            ))}
            {d.improved.confirmed_effect_per_month && <li>Подтвержденный эффект: {d.improved.confirmed_effect_per_month} в месяц</li>}
            {d.improved.processes_better.length > 0 && <li>Индекс вырос: {d.improved.processes_better.join(", ")}</li>}
          </ul>
        </Card>
        <Card className="p-5 text-sm text-ink-2">
          <h2 className="font-display text-lg font-semibold text-ink">Инвентаризация</h2>
          <p className="mt-3">
            {d.last_count
              ? `Расход по техкартам и недостачи — по последней инвентаризации ${d.last_count}.`
              : "Инвентаризаций еще не было: расход по техкартам и недостачи пока не посчитать."}
          </p>
        </Card>
      </section>
    </>
  );
}

function Kpis({ d }: { d: Digest }) {
  const rows: [string, keyof NonNullable<Digest["kpis"]>][] = [
    ["Фудкост факт", "food_cost_actual"],
    ["Фудкост по техкартам", "food_cost_theory"],
    ["Списания от выручки", "write_offs_share_of_revenue"],
    ["Выручка", "revenue"],
  ];
  if (!d.kpis) return null;
  return (
    <section aria-labelledby="kpis">
      <h2 id="kpis" className="mb-3 font-display text-lg font-semibold">Ключевые показатели</h2>
      <Card className="overflow-x-auto">
        <table className="w-full text-[13px] sm:text-sm [&_td]:px-2 [&_th]:px-2 sm:[&_td]:px-3 sm:[&_th]:px-3">
          <thead className="text-left text-xs text-ink-3">
            <tr>
              <th className="p-3 font-normal">Показатель</th>
              <th className="p-3 font-normal">Сейчас</th>
              <th className="p-3 font-normal">В прошлой сводке</th>
              {d.network_average && <th className="p-3 font-normal">В среднем по сети</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(([title, key]) => (
              <tr key={key} className="border-t border-line">
                <td className="p-3">{title}</td>
                <td className="num p-3 font-medium">{d.kpis![key] ?? "—"}</td>
                <td className="num p-3 text-ink-2">{d.kpis_previous_digest?.[key] ?? "—"}</td>
                {d.network_average && <td className="num p-3 text-ink-2">{d.network_average[key] ?? "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </section>
  );
}

function Items({
  title,
  empty,
  items,
  digest,
  canReact,
}: {
  title: string;
  empty: string;
  items: DigestItem[];
  digest: Digest;
  canReact: boolean;
}) {
  return (
    <section aria-label={title}>
      <h2 className="mb-3 font-display text-lg font-semibold">{title}</h2>
      {items.length === 0 ? (
        <p className="text-sm text-ink-3">{empty}</p>
      ) : (
        <div className="space-y-3">
          {items.map((i) => (
            <Item key={i.finding_id} i={i} digest={digest} canReact={canReact} />
          ))}
        </div>
      )}
    </section>
  );
}

function Item({ i, digest, canReact }: { i: DigestItem; digest: Digest; canReact: boolean }) {
  const { openChat } = useUi();
  const [taking, setTaking] = useState(false);
  const [disagreeing, setDisagreeing] = useState(false);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-ink-3">{i.process}</div>
          <h3 className="mt-0.5 font-medium">{i.title}</h3>
        </div>
        {i.effect_per_month && <div className="num font-display text-lg font-semibold">{i.effect_per_month} в месяц</div>}
      </div>
      <p className="mt-2 text-sm text-ink-2">{i.text}</p>
      {i.causes.length > 0 && <p className="mt-2 text-xs text-ink-3">Вероятные причины: {i.causes.join("; ")}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {i.taken ? (
          <Pill tone="brand">В работе</Pill>
        ) : (
          canReact && (
            <Button variant="primary" onClick={() => setTaking(true)}>
              Беру в работу
            </Button>
          )
        )}
        {canReact &&
          (i.disagreed ? (
            <Button variant="ghost" onClick={() => setDisagreeing(true)}>
              <ThumbsDown size={15} /> Вы не согласны — изменить
            </Button>
          ) : (
            <Button variant="ghost" onClick={() => setDisagreeing(true)}>
              <ThumbsDown size={15} /> Не согласен
            </Button>
          ))}
        <Button variant="ghost" onClick={() => openChat({ title: i.title, findingId: i.finding_id })}>
          <MessageCircle size={15} /> Обсудить с ИИ
        </Button>
      </div>
      {taking && (
        <TakeToWorkDialog
          f={{ id: i.finding_id, actions: i.actions.length ? i.actions : [i.title], effect_rub_month: null }}
          open={taking}
          onClose={() => setTaking(false)}
        />
      )}
      {disagreeing && <DisagreeDialog i={i} digestId={digest.id} onClose={() => setDisagreeing(false)} />}
    </Card>
  );
}

function DisagreeDialog({ i, digestId, onClose }: { i: DigestItem; digestId: string; onClose: () => void }) {
  const reasons = useDisagreeReasons();
  const disagree = useDisagree(i.finding_id);
  const { notify } = useUi();
  const [reason, setReason] = useState(i.disagreed ?? "");
  const [comment, setComment] = useState("");
  const needsComment = reason === "other" && !comment.trim();
  return (
    <Dialog open onClose={onClose} title="Не согласен">
      <div className="space-y-4 text-sm">
        <p className="text-ink-2">
          «{i.title}». Причину увидит управляющая компания и перепроверит находку.
        </p>
        <fieldset className="space-y-2">
          <legend className="mb-2 font-medium">Почему</legend>
          {(reasons.data ?? []).map((r) => (
            <label key={r.reason} className="flex cursor-pointer items-center gap-2.5 rounded-[10px] border border-line p-3 hover:border-brand">
              <input
                type="radio"
                name="reason"
                checked={reason === r.reason}
                onChange={() => setReason(r.reason)}
                className="accent-[#0a8f84]"
              />
              {r.title}
            </label>
          ))}
        </fieldset>
        <label className="block">
          <span className="mb-1 block font-medium">Комментарий{reason === "other" ? "" : " (необязательно)"}</span>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
            rows={3}
            className="w-full rounded-[10px] border border-line-strong p-2.5"
          />
        </label>
        {disagree.isError && <ErrorText error={disagree.error} />}
        <div className="flex flex-wrap justify-end gap-2">
          {i.disagreed && (
            <Button
              variant="ghost"
              disabled={disagree.isPending}
              onClick={() => disagree.mutate(null, { onSuccess: () => (notify("Несогласие отозвано"), onClose()) })}
            >
              Отозвать
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            disabled={!reason || needsComment || disagree.isPending}
            onClick={() =>
              disagree.mutate(
                { reason, comment: comment.trim() || undefined, digest_id: digestId },
                { onSuccess: () => (notify("Отправлено в управляющую компанию"), onClose()) },
              )
            }
          >
            Отправить
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The HQ's list of directors' «Не согласен». */
function Disagreements() {
  const list = useDisagreements(true);
  if (!list.data?.length) return null;
  return (
    <section aria-labelledby="disagreements">
      <h2 id="disagreements" className="mb-3 font-display text-lg font-semibold">
        Директора не согласны
      </h2>
      <Card>
        <ul className="divide-y divide-line">
          {list.data.map((r) => (
            <li key={r.id} className="p-4 text-sm">
              <div className="flex flex-wrap justify-between gap-2">
                <Link to="/findings/$findingId" params={{ findingId: r.finding_id }} className="font-medium hover:underline">
                  {r.finding_title}
                </Link>
                <span className="text-xs text-ink-3">
                  {r.restaurant} · {new Date(r.created_at).toLocaleDateString("ru-RU")}
                </span>
              </div>
              <div className="mt-1 text-ink-2">
                {r.reason_title}
                {r.comment && <> — «{r.comment}»</>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
