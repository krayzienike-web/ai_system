// Scripted assistant for the prototype. Every number comes from the mock data via selectors,
// mirroring the real design: the model only phrases answers around tool results.
import { FINDINGS, KPIS, RESTAURANTS, STOCK_RISKS } from "../mock/data";
import { findingById, networkKpis, restaurantByCode, restaurantFindings } from "../mock/selectors";
import { pct, perMonth, rub } from "./format";

const perMonthOf = perMonth;
import type { Viewer } from "./useViewer";

export interface ChatAnswer {
  text: string;
  table?: { columns: string[]; rows: string[][] };
  sourceFindingId?: string;
  source?: string;
  suggestions?: string[];
}

const SUGGESTIONS_DIRECTOR = [
  "Почему у меня вырос фудкост?",
  "Где я переплачиваю?",
  "Что закончится до поставки?",
  "Как снизить списания?",
];
const SUGGESTIONS_HQ = [
  "Сравни рестораны по фудкосту",
  "Где сеть переплачивает?",
  "Что закончится до поставки?",
  "Какие проверки сработали?",
];

export const suggestionsFor = (viewer: Viewer) => (viewer.isHq ? SUGGESTIONS_HQ : SUGGESTIONS_DIRECTOR);

const scope = (viewer: Viewer) =>
  viewer.isHq ? RESTAURANTS.map((r) => r.code) : viewer.restaurantCode ? [viewer.restaurantCode] : [];

const name = (code: string | null) => (code ? (restaurantByCode(code)?.name ?? code) : "Вся сеть");

export function answer(question: string, viewer: Viewer, findingId?: string): ChatAnswer {
  const q = question.toLowerCase();
  const codes = scope(viewer);

  const mentionsOther =
    !viewer.isHq &&
    (/сравни|другие|соседн|остальн/.test(q) ||
      RESTAURANTS.some(
        (r) => r.code !== viewer.restaurantCode && (q.includes(r.code.toLowerCase()) || q.includes(r.name.split(" ").pop()!.toLowerCase().slice(0, 5))),
      ));
  if (mentionsOther) {
    const avg = networkKpis();
    const own = KPIS[viewer.restaurantCode!]!;
    return {
      text: "Данные других ресторанов вам недоступны — могу сравнить ваш ресторан со средним по сети.",
      table: {
        columns: ["Показатель", "Ваш ресторан", "Среднее по сети"],
        rows: [
          ["Фудкост факт", pct(own.foodCostActual), pct(avg.foodCostActual)],
          ["Списания, % выручки", pct(own.writeoffsPct), pct(avg.writeoffsPct)],
        ],
      },
      source: "период между инвентаризациями 03.08–01.10",
    };
  }

  if (/за год/.test(q) && findingId) {
    const f = findingById(findingId);
    if (f?.effectRubMonth) {
      return { text: `${perMonthOf(f.effectRubMonth)} — это около ${rub(f.effectRubMonth * 12)} в год.`, sourceFindingId: f.id };
    }
  }

  if (findingId && !/фудкост|переплач|законч|дефицит|списан|эксперимент/.test(q)) {
    const f = findingById(findingId);
    if (f) {
      return {
        text: `${f.summary}\n\nВероятные причины: ${f.causes.length ? f.causes.join("; ") : "не выявлены"}.\n\nЧто можно сделать: ${f.actions.join("; ")}.`,
        sourceFindingId: f.id,
        suggestions: ["Сколько это в рублях за год?", "С чего начать?"],
      };
    }
  }

  if (/фудкост/.test(q)) {
    const avg = networkKpis();
    const rows = codes.map((c) => {
      const k = KPIS[c]!;
      return [name(c), pct(k.foodCostActual), pct(k.foodCostTheoretical), `${(k.foodCostActual - k.foodCostTheoretical).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} пункта`];
    });
    if (!viewer.isHq) rows.push(["Среднее по сети", pct(avg.foodCostActual), pct(avg.foodCostTheoretical), "—"]);
    const top = FINDINGS.filter((f) => codes.includes(f.restaurantId ?? "") && f.kind === "problem" && f.process === "production")[0];
    return {
      text: `Фактический фудкост считаем между двумя инвентаризациями (03.08–01.10). Разница с фудкостом по техкартам — это то, что ушло сверх нормы.${top ? ` Главный вклад — «${top.title}» (${perMonthOf(top.effectRubMonth ?? 0)}).` : ""}`,
      table: { columns: ["Ресторан", "Фактический", "По техкартам", "Разница"], rows },
      sourceFindingId: top?.id,
      source: "продажи r_keeper, склад iiko, закупки 1С за период 03.08–01.10",
    };
  }

  if (/переплач|цен|поставщ/.test(q)) {
    const items = FINDINGS.filter((f) => codes.includes(f.restaurantId ?? "") && f.process === "purchasing" && f.status !== "resolved");
    return {
      text: `Нашел ${items.length} позиций, где закупка дороже среднего или лучшей цены сети.`,
      table: {
        columns: viewer.isHq ? ["Ресторан", "Позиция", "Эффект"] : ["Позиция", "Цена", "Эффект"],
        rows: items.map((f) =>
          viewer.isHq
            ? [name(f.restaurantId), f.title, perMonthOf(f.effectRubMonth ?? 0)]
            : [f.title, `${f.metric.value} (${f.metric.benchmark})`, perMonthOf(f.effectRubMonth ?? 0)],
        ),
      },
      source: "закупки из 1С за 12 недель",
    };
  }

  if (/законч|дефицит|запас|хватит/.test(q)) {
    const risks = STOCK_RISKS.filter((r) => codes.includes(r.restaurantId));
    return {
      text: risks.length ? "Эти позиции могут закончиться раньше ближайшей поставки:" : "Рисков дефицита на ближайшие дни не вижу.",
      table: {
        columns: [...(viewer.isHq ? ["Ресторан"] : []), "Товар", "Хватит на", "Поставка через", "Поставщик"],
        rows: risks.map((r) => [...(viewer.isHq ? [name(r.restaurantId)] : []), r.product, `${r.daysLeft} дн.`, `${r.nextDeliveryInDays} дн.`, r.supplier]),
      },
      source: "прогноз продаж × техкарты, остатки iiko на 18.10",
    };
  }

  if (/списан/.test(q)) {
    const items = codes.flatMap((c) => restaurantFindings(c).problems.concat(restaurantFindings(c).opportunities)).filter((f) => ["writeoffs", "storage"].includes(f.process));
    return {
      text: "Основные резервы по списаниям — в заказе скоропорта под реальное потребление. Подтвержденный пример в сети: малые партии зелени снизили списания на 48%.",
      table: { columns: ["Что", "Эффект"], rows: items.map((f) => [`${viewer.isHq ? `${name(f.restaurantId)}: ` : ""}${f.title}`, perMonthOf(f.effectRubMonth ?? 0)]) },
      source: "акты списания iiko за 12 недель",
    };
  }

  if (/эксперимент/.test(q)) {
    return {
      text: "Две проверки завершены. «Малые партии зелени» на Невском сработала — плюс 5,2 тыс ₽ в месяц (скорее всего от 3 до 7 тыс). «Дозаторы для соусов» на Арбате не сработала: расход соусов не изменился. Еще одна идет, пять ждут запуска.",
      source: "раздел «Проверки»",
    };
  }

  return {
    text: "В прототипе я отвечаю на вопросы о фудкосте, ценах закупки, списаниях, рисках дефицита и проверках. В рабочей версии отвечу на любой вопрос по данным в пределах ваших прав.",
    suggestions: suggestionsFor(viewer),
  };
}
