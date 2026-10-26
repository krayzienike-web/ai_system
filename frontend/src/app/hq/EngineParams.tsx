import { RotateCcw } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useEngineParams, useSaveEngineParams } from "../../api/hooks";
import type { EngineParam } from "../../api/types";
import {
  Button,
  cx,
  QuestionBlock,
  Reveal,
  Skeleton,
} from "../../ds/primitives";
import { useViewer } from "../../lib/useViewer";
import { usePrototype } from "../../state/prototype";

const MODULES: { code: string; title: string }[] = [
  { code: "ALL", title: "Общие для всех модулей" },
  { code: "M1", title: "M1 · Потери по техкартам" },
  { code: "M2", title: "M2 · Фудкост блюд" },
  { code: "M3", title: "M3 · Закупочные цены" },
];

const show = (v: string) => v.replace(".", ",");
const same = (a: string, b: string) =>
  Number(a.replace(",", ".")) === Number(b.replace(",", "."));

/** The detectors' thresholds of this network: a block per module, folded; saved values apply at the next run. */
export function EngineParamsSection() {
  const params = useEngineParams();
  if (params.isError)
    return (
      <p className="text-loss">Не получилось загрузить параметры движка</p>
    );
  if (!params.data) return <Skeleton className="h-40" />;
  return (
    <EngineParamsForm key={JSON.stringify(params.data)} params={params.data} />
  );
}

function EngineParamsForm({ params }: { params: EngineParam[] }) {
  const viewer = useViewer();
  const save = useSaveEngineParams();
  const { notify } = usePrototype();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const readOnly = !viewer?.isAdmin;
  const changed = Object.entries(draft).filter(
    ([k, v]) => !same(v, params.find((p) => p.key === k)!.value),
  );

  const submit = (values: Record<string, string | null>) =>
    save.mutate(values, {
      onSuccess: () => {
        setDraft({});
        notify(
          "Параметры сохранены. Нажмите «Пересчитать находки» на экране «Проверка находок»",
        );
      },
    });

  return (
    <Reveal index={4}>
      <QuestionBlock
        question="Какие пороги использует движок?"
        answer="Когда находка считается находкой: суммы, проценты, окна сравнения. Значения по умолчанию описаны в документе по движку; здесь их можно поменять для своей сети. Новые значения применятся при следующем пересчете находок."
      >
        <div className="space-y-3">
          {MODULES.map((m) => {
            const items = params.filter((p) => p.module === m.code);
            if (!items.length) return null;
            const own = items.filter((p) => !same(p.value, p.default)).length;
            return (
              <details
                key={m.code}
                className="group rounded-[12px] border border-line"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3 text-sm font-medium">
                  <span>
                    {m.title}
                    <span className="ml-2 text-ink-3">· {items.length}</span>
                    {own > 0 && (
                      <span className="ml-2 rounded-full bg-brand-soft px-2 py-0.5 text-xs text-brand-strong">
                        своих значений: {own}
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-brand-strong group-open:hidden">
                    Показать
                  </span>
                  <span className="hidden text-xs text-brand-strong group-open:inline">
                    Скрыть
                  </span>
                </summary>
                <ul className="divide-y divide-line border-t border-line">
                  {items.map((p) => {
                    const value = draft[p.key] ?? show(p.value);
                    const edited =
                      p.key in draft && !same(draft[p.key]!, p.value);
                    const custom = !same(p.value, p.default);
                    return (
                      <li
                        key={p.key}
                        className={cx(
                          "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3",
                          edited && "bg-warn-soft",
                        )}
                      >
                        <label
                          htmlFor={`ep-${p.key}`}
                          className="text-sm font-medium"
                        >
                          {p.title}
                        </label>
                        <span className="flex items-center gap-1.5">
                          <input
                            id={`ep-${p.key}`}
                            value={value}
                            inputMode="decimal"
                            disabled={readOnly}
                            onChange={(e) =>
                              setDraft((d) => ({
                                ...d,
                                [p.key]: e.target.value,
                              }))
                            }
                            className="num h-9 w-24 rounded-[10px] border border-line-strong bg-surface px-2 text-right text-sm outline-none focus:border-brand disabled:bg-paper"
                          />
                          <span className="w-20 text-xs text-ink-3">
                            {p.unit}
                          </span>
                        </span>
                        <span className="col-span-2 text-xs text-ink-3">
                          {p.meaning && `${p.meaning} · `}по умолчанию{" "}
                          {show(p.default)} {p.unit}
                          {custom && !readOnly && (
                            <button
                              type="button"
                              onClick={() => submit({ [p.key]: null })}
                              className="ml-2 inline-flex items-center gap-1 text-brand-strong hover:underline"
                            >
                              <RotateCcw size={11} /> вернуть
                            </button>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </details>
            );
          })}
          {!readOnly && (
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                disabled={!changed.length || save.isPending}
                onClick={() =>
                  submit(
                    Object.fromEntries(
                      changed.map(([k, v]) => [k, v.replace(",", ".")]),
                    ),
                  )
                }
              >
                Сохранить параметры
                {changed.length ? ` (${changed.length})` : ""}
              </Button>
              {save.isError && (
                <span className="text-sm text-loss">
                  {save.error instanceof ApiError
                    ? save.error.message
                    : "Не получилось сохранить"}
                </span>
              )}
            </div>
          )}
        </div>
      </QuestionBlock>
    </Reveal>
  );
}
