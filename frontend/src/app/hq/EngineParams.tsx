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
import { MODULE_TITLE } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";

/** The blocks follow the parameters the server has: a new module's thresholds appear without a UI change. */
const modulesOf = (params: EngineParam[]) =>
  [...new Set(params.map((p) => p.module))].map((code) => ({
    code,
    title: code === "ALL" ? "Общие для всех модулей" : `${code} · ${MODULE_TITLE[code] ?? ""}`,
  }));

const show = (v: string) => v.replace(".", ",");
const same = (a: string, b: string) =>
  Number(a.replace(",", ".")) === Number(b.replace(",", "."));
/** Error text for a typed value, or null: the same range the server checks. */
export function rangeError(p: EngineParam, typed: string): string | null {
  const n = Number(typed.trim().replace(",", "."));
  if (!typed.trim() || !Number.isFinite(n)) return "нужно число";
  if (n < Number(p.low) || n > Number(p.high))
    return `от ${show(p.low)} до ${show(p.high)}`;
  return null;
}

/** The detectors' thresholds of this network: a block per module, folded; saved values apply at the next run. */
export function EngineParamsSection() {
  const params = useEngineParams();
  if (params.isError)
    return (
      <p className="text-loss">Не получилось загрузить параметры движка</p>
    );
  if (!params.data) return <Skeleton className="h-40" />;
  return <EngineParamsForm params={params.data} />;
}

function EngineParamsForm({ params }: { params: EngineParam[] }) {
  const viewer = useViewer();
  const save = useSaveEngineParams();
  const { notify } = useUi();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const readOnly = !viewer?.isAdmin;
  const byKey = new Map(params.map((p) => [p.key, p]));
  const changed = Object.entries(draft).filter(
    ([k, v]) => v.trim() === "" || !same(v, byKey.get(k)!.value),
  );
  const invalid = changed.filter(([k, v]) => rangeError(byKey.get(k)!, v));

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
          {modulesOf(params).map((m) => {
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
                    const atDefault = same(value, p.default);
                    const custom = !same(p.value, p.default);
                    const error = edited || (p.key in draft && draft[p.key]!.trim() === "")
                      ? rangeError(p, draft[p.key]!)
                      : null;
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
                            aria-invalid={Boolean(error)}
                            aria-describedby={error ? `ep-${p.key}-error` : undefined}
                            onChange={(e) =>
                              setDraft((d) => ({
                                ...d,
                                [p.key]: e.target.value,
                              }))
                            }
                            className={cx(
                              "num h-9 w-24 rounded-[10px] border bg-surface px-2 text-right text-sm outline-none focus:border-brand disabled:bg-paper",
                              error ? "border-loss" : "border-line-strong",
                            )}
                          />
                          <span className="w-20 text-xs text-ink-3">
                            {p.unit}
                          </span>
                        </span>
                        {error && (
                          <span
                            id={`ep-${p.key}-error`}
                            className="col-span-2 text-xs text-loss"
                          >
                            {error}
                          </span>
                        )}
                        <span className="col-span-2 text-xs text-ink-3">
                          {p.meaning && `${p.meaning} · `}по умолчанию{" "}
                          {show(p.default)} {p.unit}
                          {(custom || edited) && !atDefault && !readOnly && (
                            <button
                              type="button"
                              // Only fills in the default: saved together with the other edits.
                              onClick={() =>
                                setDraft((d) => ({ ...d, [p.key]: show(p.default) }))
                              }
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
                disabled={!changed.length || invalid.length > 0 || save.isPending}
                onClick={() =>
                  submit(
                    Object.fromEntries(
                      changed.map(([k, v]) => {
                        const p = byKey.get(k)!;
                        // The default typed back in: the network has no own value any more.
                        return [k, same(v, p.default) ? null : v.replace(",", ".")];
                      }),
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
