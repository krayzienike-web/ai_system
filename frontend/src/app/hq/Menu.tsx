// «Меню» (stage 11, docs/12 «Меню-инжиниринг»): popularity × margin of every dish, by category — the matrix
// the HQ looks at when it plans the next menu. Every number is the server's (`/reports/menu`).
import { useState } from "react";

import { useMenuMatrix, useRestaurants } from "../../api/hooks";
import type { MenuDish } from "../../api/types";
import { Card, cx, EmptyState, LoadError, PageTitle, Reveal, Skeleton } from "../../ds/primitives";
import { ddmm, num, pct } from "../../lib/format";

/** A menu price as it is printed in the menu: whole rubles, never «1,5 тыс». */
const money = (value: string) => `${Math.round(Number(value)).toLocaleString("ru-RU")} ₽`;

const QUADRANTS = {
  star: { title: "Звезды", hint: "Популярны и выгодны: держать качество и место в меню", tone: "bg-gain-soft" },
  plowhorse: {
    title: "Рабочие лошадки",
    hint: "Популярны, но мало приносят: поднять цену в следующем меню или снизить себестоимость",
    tone: "bg-warn-soft",
  },
  puzzle: { title: "Загадки", hint: "Выгодны, но берут редко: продвигать — официанты, место в меню, фото", tone: "bg-info-soft" },
  dog: { title: "Собаки", hint: "Берут редко и приносят мало: переделать или убрать", tone: "bg-loss-soft" },
} as const;

// Popular dishes on top, high margin on the left: the usual reading of the matrix.
const GRID: (keyof typeof QUADRANTS)[] = ["star", "plowhorse", "puzzle", "dog"];

const select =
  "h-10 rounded-[10px] border border-line-strong bg-surface px-3 text-sm text-ink outline-none transition hover:border-ink-3 focus:border-brand";

function Cell({ quadrant, dishes }: { quadrant: keyof typeof QUADRANTS; dishes: MenuDish[] }) {
  const q = QUADRANTS[quadrant];
  return (
    <div className={cx("rounded-[12px] p-3", q.tone)}>
      <div className="text-sm font-semibold text-ink">{q.title}</div>
      <div className="text-xs text-ink-2">{q.hint}</div>
      {dishes.length ? (
        <ul className="mt-2 space-y-0.5 text-sm">
          {dishes.map((d) => (
            <li key={d.code}>{d.name}</li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-sm text-ink-3">нет блюд</div>
      )}
    </div>
  );
}

export function MenuPage() {
  const restaurants = useRestaurants();
  const [where, setWhere] = useState("");
  const query = useMenuMatrix(where || null);
  return (
    <div className="mx-auto max-w-[1100px]">
      <PageTitle
        title="Меню: популярность и маржа"
        subtitle="Блюда каждой категории по тому, как часто их берут и сколько они приносят с порции. Цены закупки и техкарты — сети"
      />
      <div className="mb-4">
        <select value={where} onChange={(e) => setWhere(e.target.value)} aria-label="Чьи продажи" className={select}>
          <option value="">Продажи всей сети</option>
          {(restaurants.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              Продажи: {r.name}
            </option>
          ))}
        </select>
      </div>
      {query.isError && !query.data ? (
        <LoadError error={query.error} title="Не получилось загрузить меню" retry={() => void query.refetch()} />
      ) : !query.data ? (
        <Skeleton className="h-96" />
      ) : !query.data.categories.length ? (
        <EmptyState title="Пока не из чего считать">Нужны продажи, техкарты и закупки за последние 4 недели.</EmptyState>
      ) : (
        <>
          <p className="mb-4 text-sm text-ink-2">
            {query.data.since && query.data.until && `${ddmm(query.data.since)}–${ddmm(query.data.until)}. `}
            Популярное блюдо — то, что берут не реже 70% от равной доли категории; выгодное — с маржой с порции не ниже
            средней по категории.
          </p>
          <div className="space-y-4">
            {query.data.categories.map((c, i) => (
              <Reveal key={c.name} index={i}>
                <Card className="p-5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="font-display text-lg font-semibold">{c.name}</h2>
                    <div className="text-sm text-ink-3">
                      маржа в среднем {money(c.margin)} с порции · популярно от {pct(Number(c.popular_from) * 100, 0)}{" "}
                      продаж категории
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2" role="group" aria-label={`Матрица: ${c.name}`}>
                    {GRID.map((g) => (
                      <Cell key={g} quadrant={g} dishes={c.dishes.filter((d) => d.quadrant === g)} />
                    ))}
                  </div>
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[560px] text-sm">
                      <thead className="text-left text-ink-3">
                        <tr>
                          <th className="py-1 pr-3 font-normal">Блюдо</th>
                          <th className="py-1 pr-3 text-right font-normal">Цена</th>
                          <th className="py-1 pr-3 text-right font-normal">Себестоимость</th>
                          <th className="py-1 pr-3 text-right font-normal">Маржа</th>
                          <th className="py-1 pr-3 text-right font-normal">Фудкост</th>
                          <th className="py-1 text-right font-normal">Порций в месяц · доля</th>
                        </tr>
                      </thead>
                      <tbody>
                        {c.dishes.map((d) => (
                          <tr key={d.code} className="border-t border-line">
                            <td className="py-1.5 pr-3">
                              {d.name} <span className="text-ink-3">· {QUADRANTS[d.quadrant].title.toLowerCase()}</span>
                            </td>
                            <td className="num py-1.5 pr-3 text-right">{money(d.price)}</td>
                            <td className="num py-1.5 pr-3 text-right">{money(d.cost)}</td>
                            <td className="num py-1.5 pr-3 text-right">{money(d.margin)}</td>
                            <td className="num py-1.5 pr-3 text-right">{pct(Number(d.food_cost) * 100)}</td>
                            <td className="num py-1.5 text-right">
                              {num(Number(d.portions_month))} · {pct(Number(d.share) * 100, 0)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </Reveal>
            ))}
          </div>
          {query.data.not_counted.length > 0 && (
            <p className="mt-4 text-sm text-ink-3">
              Не посчитаны — нет цены, техкарты, цены ингредиента или продаж за 4 недели:{" "}
              {query.data.not_counted.join(", ")}.
            </p>
          )}
        </>
      )}
    </div>
  );
}
