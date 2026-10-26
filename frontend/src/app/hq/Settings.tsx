import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useNorms, useSaveNorms } from "../../api/hooks";
import type { Norms, ReasonKind, WriteOffReason } from "../../api/types";
import {
  Button,
  PageTitle,
  QuestionBlock,
  Reveal,
  Skeleton,
} from "../../ds/primitives";
import { useViewer } from "../../lib/useViewer";
import { usePrototype } from "../../state/prototype";

const KINDS: { kind: ReasonKind; title: string }[] = [
  { kind: "loss", title: "Потеря" },
  { kind: "planned", title: "Плановый расход" },
  { kind: "shortage", title: "Закрытие недостачи" },
];

/** "3.00" → "3", "1.50" → "1,5": percentages as people write them. */
const show = (v: string | undefined) =>
  v === undefined ? "" : String(Number(v)).replace(".", ",");
const send = (v: string) => v.trim().replace(",", ".");

interface Draft {
  food: string;
  foodBy: Record<string, string>;
  loss: string;
  lossBy: Record<string, string>;
  reasons: (WriteOffReason & { synonymsText: string })[];
}

const draftOf = (n: Norms): Draft => ({
  food: show(n.food_cost_target_pct),
  foodBy: Object.fromEntries(
    Object.entries(n.food_cost_by_category).map(([k, v]) => [k, show(v)]),
  ),
  loss: show(n.loss_default_pct),
  lossBy: Object.fromEntries(
    Object.entries(n.loss_by_category).map(([k, v]) => [k, show(v)]),
  ),
  reasons: n.write_off_reasons.map((r) => ({
    ...r,
    synonymsText: r.synonyms.join(", "),
  })),
});

const filled = (m: Record<string, string>) =>
  Object.fromEntries(
    Object.entries(m)
      .filter(([, v]) => v.trim() !== "")
      .map(([k, v]) => [k, send(v)]),
  );

export function SettingsPage() {
  const norms = useNorms();
  return (
    <div className="mx-auto max-w-[760px] space-y-6">
      <PageTitle
        title="Нормы и настройки"
        subtitle="По этим нормам су-шеф решает, что считать проблемой"
      />
      {norms.data ? (
        // Re-mounts after a save, so the form always starts from what is stored.
        <NormsForm key={JSON.stringify(norms.data)} norms={norms.data} />
      ) : norms.isError ? (
        <p className="text-loss">
          Не получилось загрузить нормы. Обновите страницу
        </p>
      ) : (
        <Skeleton className="h-64" />
      )}
    </div>
  );
}

function PctInput({
  value,
  onChange,
  label,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  placeholder?: string;
  disabled: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="decimal"
        aria-label={label}
        placeholder={placeholder}
        disabled={disabled}
        className="num h-9 w-16 rounded-[10px] border border-line-strong bg-surface px-2 text-right outline-none focus:border-brand disabled:bg-paper"
      />
      <span className="text-ink-3">%</span>
    </span>
  );
}

function NormsForm({ norms }: { norms: Norms }) {
  const viewer = useViewer();
  const { notify } = usePrototype();
  const save = useSaveNorms();
  const [d, setD] = useState<Draft>(() => draftOf(norms));
  const readOnly = !viewer?.isAdmin;
  const lossCategories = [
    ...new Set([
      ...norms.product_categories,
      ...Object.keys(norms.loss_by_category),
    ]),
  ].sort();
  const foodCategories = [
    ...new Set([
      ...norms.menu_categories,
      ...Object.keys(norms.food_cost_by_category),
    ]),
  ].sort();
  const setReason = (i: number, patch: Partial<Draft["reasons"][number]>) =>
    setD((x) => ({
      ...x,
      reasons: x.reasons.map((r, j) => (j === i ? { ...r, ...patch } : r)),
    }));

  const submit = () =>
    save.mutate(
      {
        food_cost_target_pct: send(d.food),
        food_cost_by_category: filled(d.foodBy),
        loss_default_pct: send(d.loss),
        loss_by_category: filled(d.lossBy),
        write_off_reasons: d.reasons.map(({ synonymsText, ...r }) => ({
          ...r,
          synonyms: synonymsText
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        })),
      },
      {
        onSuccess: () =>
          notify("Нормы сохранены. Находки пересчитаются по новым нормам"),
      },
    );

  return (
    <>
      {readOnly && (
        <p className="rounded-[12px] bg-info-soft px-4 py-3 text-sm text-info">
          Нормы меняет администратор управляющей компании. Здесь видно, по каким
          значениям считаются находки.
        </p>
      )}
      <Reveal>
        <QuestionBlock
          question="Какой фудкост вы считаете нормальным?"
          answer="Блюда с фудкостом выше этой цифры су-шеф предложит пересмотреть по цене или техкарте. Для отдельных категорий меню можно задать свою цифру."
        >
          <div className="flex items-center justify-between gap-3 border-b border-line pb-3">
            <span className="font-medium">По всей сети</span>
            <PctInput
              value={d.food}
              onChange={(food) => setD((x) => ({ ...x, food }))}
              label="Целевой фудкост по сети"
              disabled={readOnly}
            />
          </div>
          <ul className="mt-2 divide-y divide-line text-sm">
            {foodCategories.map((c) => (
              <li
                key={c}
                className="flex items-center justify-between gap-3 py-2"
              >
                <span>{c}</span>
                <PctInput
                  value={d.foodBy[c] ?? ""}
                  onChange={(v) =>
                    setD((x) => ({ ...x, foodBy: { ...x.foodBy, [c]: v } }))
                  }
                  label={`Целевой фудкост: ${c}`}
                  placeholder={d.food}
                  disabled={readOnly}
                />
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-3">Пустое поле — как по сети.</p>
        </QuestionBlock>
      </Reveal>

      <Reveal index={1}>
        <QuestionBlock
          question="Сколько продукта можно терять сверх техкарты?"
          answer="Если расход выше нормы больше чем на эту величину, су-шеф покажет проблему. Учитывает очистку, зачистку, разделку и розлив."
        >
          <div className="flex items-center justify-between gap-3 border-b border-line pb-3">
            <span className="font-medium">Остальные категории</span>
            <PctInput
              value={d.loss}
              onChange={(loss) => setD((x) => ({ ...x, loss }))}
              label="Допустимые потери по умолчанию"
              disabled={readOnly}
            />
          </div>
          <ul className="mt-2 divide-y divide-line text-sm">
            {lossCategories.map((c) => (
              <li
                key={c}
                className="flex items-center justify-between gap-3 py-2"
              >
                <span>{c}</span>
                <PctInput
                  value={d.lossBy[c] ?? ""}
                  onChange={(v) =>
                    setD((x) => ({ ...x, lossBy: { ...x.lossBy, [c]: v } }))
                  }
                  label={`Допустимые потери: ${c}`}
                  placeholder={d.loss}
                  disabled={readOnly}
                />
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-3">
            Пустое поле — значение для остальных категорий.
          </p>
        </QuestionBlock>
      </Reveal>

      <Reveal index={2}>
        <QuestionBlock
          question="Какие причины списания вы используете?"
          answer="Су-шеф сводит причины из выгрузок к этому списку. Сейчас стоит стандартный список — замените его причинами из регламента сети. Незнакомая причина попадает в «Прочее», а отчет о загрузке подскажет добавить ее сюда."
        >
          <ul className="space-y-3">
            {d.reasons.map((r, i) => (
              <li
                key={r.code}
                className="rounded-[12px] border border-line p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    value={r.title}
                    onChange={(e) => setReason(i, { title: e.target.value })}
                    aria-label="Причина"
                    disabled={readOnly}
                    className="h-9 min-w-[180px] flex-1 rounded-[10px] border border-line-strong bg-surface px-2 text-sm font-medium outline-none focus:border-brand disabled:bg-paper"
                  />
                  <select
                    value={r.kind}
                    onChange={(e) =>
                      setReason(i, { kind: e.target.value as ReasonKind })
                    }
                    aria-label={`Вид: ${r.title}`}
                    disabled={readOnly}
                    className="h-9 rounded-[10px] border border-line-strong bg-surface px-2 text-sm outline-none focus:border-brand disabled:bg-paper"
                  >
                    {KINDS.map((k) => (
                      <option key={k.kind} value={k.kind}>
                        {k.title}
                      </option>
                    ))}
                  </select>
                  {!readOnly && r.code !== "other" && (
                    <button
                      type="button"
                      onClick={() =>
                        setD((x) => ({
                          ...x,
                          reasons: x.reasons.filter((_, j) => j !== i),
                        }))
                      }
                      aria-label={`Удалить причину ${r.title}`}
                      className="grid h-9 w-9 place-items-center rounded-[10px] text-ink-3 hover:bg-loss-soft hover:text-loss"
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </div>
                {r.code === "other" ? (
                  <p className="mt-2 text-xs text-ink-3">
                    Сюда попадает все, что не узнали. Удалить нельзя.
                  </p>
                ) : (
                  <input
                    value={r.synonymsText}
                    onChange={(e) =>
                      setReason(i, { synonymsText: e.target.value })
                    }
                    aria-label={`Как пишут в выгрузке: ${r.title}`}
                    placeholder="Как пишут в выгрузке, через запятую"
                    disabled={readOnly}
                    className="mt-2 h-9 w-full rounded-[10px] border border-line bg-surface px-2 text-sm text-ink-2 outline-none focus:border-brand disabled:bg-paper"
                  />
                )}
              </li>
            ))}
          </ul>
          {!readOnly && (
            <Button
              size="sm"
              className="mt-3"
              onClick={() =>
                setD((x) => ({
                  ...x,
                  reasons: [
                    ...x.reasons.filter((r) => r.code !== "other"),
                    {
                      code: `custom-${Date.now()}`,
                      title: "",
                      kind: "loss",
                      synonyms: [],
                      synonymsText: "",
                    },
                    ...x.reasons.filter((r) => r.code === "other"),
                  ],
                }))
              }
            >
              <Plus size={14} /> Добавить причину
            </Button>
          )}
          <p className="mt-3 text-xs text-ink-3">
            «Потеря» — деньги, которые можно вернуть. «Плановый расход» —
            питание персонала, проработки: не потеря, но учитывается. «Закрытие
            недостачи» — списание, которым закрывают минус после инвентаризации:
            су-шеф проверит его отдельно.
          </p>
        </QuestionBlock>
      </Reveal>

      {!readOnly && (
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={submit} disabled={save.isPending}>
            Сохранить нормы
          </Button>
          {save.isError && (
            <span className="text-sm text-loss">
              {save.error instanceof ApiError
                ? save.error.message
                : "Не получилось сохранить, попробуйте еще раз"}
            </span>
          )}
        </div>
      )}
    </>
  );
}
