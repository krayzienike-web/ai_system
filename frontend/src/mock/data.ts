// Demo data for the UX prototype. Restaurants are keyed by code (R01–R03) and match the demo seed.
// Totals (money on the table, process statuses) are computed in selectors.ts, never hard-coded here.

import type {
  DataSourceFreshness,
  Experiment,
  Finding,
  Improvement,
  Kpis,
  RestaurantInfo,
  StockRisk,
  Task,
  WeeklyTrend,
} from "./types";

export const PERIOD = {
  week: "12–18 октября",
  dataUntil: "18.10.2026",
  lastInventory: "01.10.2026",
  prevInventory: "03.08.2026",
  nextInventory: "02.11.2026",
};

export const RESTAURANTS: RestaurantInfo[] = [
  { id: "R01", code: "R01", name: "Ресторан на Тверской", city: "Москва", revenueMonth: 6_200_000 },
  { id: "R02", code: "R02", name: "Ресторан на Арбате", city: "Москва", revenueMonth: 5_100_000 },
  { id: "R03", code: "R03", name: "Ресторан на Невском", city: "Санкт-Петербург", revenueMonth: 4_400_000 },
];

const INVENTORY_PERIODS = ["02.04–05.06", "05.06–03.08", "03.08–01.10"];
const WEEKS = ["27.07", "03.08", "10.08", "17.08", "24.08", "31.08", "07.09", "14.09", "21.09", "28.09", "05.10", "12.10"];

export const FINDINGS: Finding[] = [
  // ---------------------------------------------------------------- R01 · problems
  {
    id: "r01-mozzarella",
    kind: "problem",
    process: "production",
    restaurantId: "R01",
    title: "Перерасход моцареллы по ТТК",
    effectRubMonth: 38_000,
    confidence: "high",
    confidenceNote: "Две полные инвентаризации (03.08 и 01.10), продажи и приходы без пропусков",
    metric: { label: "Расход сверх ТТК", value: "9,1%", benchmark: "в среднем по сети 3,4%", norm: "норма до 2%" },
    summary:
      "За период 03.08–01.10 фактический расход моцареллы на 84 кг больше, чем по ТТК проданных блюд, с учетом документированных списаний. Отклонение растет третий период подряд.",
    causes: [
      "Порционирование «на глаз» на раздаче пиццы: больше всего моцареллы уходит в «Маргариту» и «Четыре сыра»",
      "Неучтенные списания (брак, питание персонала) без оформления акта",
      "Отклонение растет с июня — совпадает со сменой состава кухни",
    ],
    actions: [
      "Две недели контрольного взвешивания сыра на раздаче (весы на станции пиццы)",
      "Фото-стандарт порции для «Маргариты» и «Четырех сыров» у станции",
      "Оформлять акт на каждый брак и питание персонала",
    ],
    chart: {
      title: "Расход сверх ТТК по периодам между инвентаризациями",
      unit: "%",
      labels: INVENTORY_PERIODS,
      restaurant: [3.8, 6.2, 9.1],
      networkAvg: [3.1, 3.3, 3.4],
      norm: 2,
      normLabel: "Норма 2%",
    },
    evidence: {
      title: "Баланс моцареллы, 03.08–01.10",
      columns: ["Показатель", "Кол-во, кг", "Сумма, ₽"],
      rows: [
        ["Остаток на 03.08 (инвентаризация)", 38, 34_390],
        ["Приход (накладные iiko)", 1_012, 915_860],
        ["Остаток на 01.10 (инвентаризация)", 43, 38_915],
        ["Фактический расход", 1_007, 911_335],
        ["Расход по ТТК проданных блюд", 920, 832_600],
        ["Списано по актам", 3, 2_715],
        ["Не объяснено", 84, 76_020],
      ],
    },
    status: "in_experiment",
  },
  {
    id: "r01-cream",
    kind: "problem",
    process: "purchasing",
    restaurantId: "R01",
    title: "Сливки 33% дороже среднего по сети",
    effectRubMonth: 21_000,
    confidence: "high",
    confidenceNote: "12 недель закупок по данным 1С:ERP",
    metric: { label: "Цена за литр", value: "412 ₽", benchmark: "в среднем по сети 361 ₽" },
    summary:
      "Сливки 33% закупаются у «Молочного двора» по 412 ₽/л — на 14% выше средней цены сети. При объеме около 410 л в месяц переплата около 21 тыс ₽.",
    causes: [
      "Цена поставщика выросла в августе и не пересматривалась",
      "Нет сравнения с ценами других поставщиков сети при заказе",
    ],
    actions: [
      "Запросить у «Молочного двора» цену на уровне рынка",
      "Если не снизят — перейти к поставщику сети с ценой 352–365 ₽/л",
    ],
    chart: {
      title: "Цена сливок 33%, ₽/л по неделям",
      unit: "₽",
      labels: WEEKS,
      restaurant: [365, 368, 398, 405, 405, 410, 410, 412, 412, 412, 412, 412],
      networkAvg: [358, 359, 360, 360, 361, 361, 360, 361, 362, 361, 361, 361],
    },
    evidence: {
      title: "Последние приходы (1С:ERP)",
      columns: ["Дата", "Поставщик", "Кол-во, л", "Цена, ₽/л", "Сумма, ₽"],
      rows: [
        ["16.10", "Молочный двор", 96, 412, 39_552],
        ["09.10", "Молочный двор", 104, 412, 42_848],
        ["02.10", "Молочный двор", 98, 412, 40_376],
        ["25.09", "Молочный двор", 110, 412, 45_320],
      ],
    },
    status: "new",
  },
  {
    id: "r01-greens",
    kind: "problem",
    process: "storage",
    restaurantId: "R01",
    title: "Списания зелени в 3,3 раза выше среднего по сети",
    effectRubMonth: 10_000,
    confidence: "high",
    confidenceNote: "Акты списания iiko за 12 недель",
    metric: { label: "Списания зелени", value: "1,85% выручки кухни", benchmark: "в среднем по сети 0,56%" },
    summary:
      "Руккола, базилик и шпинат списываются каждую неделю по причине «истек срок». Закупка идет партиями на 5–6 дней при сроке хранения 3 дня.",
    causes: ["Партия заказа больше потребления до конца срока годности", "Нет ротации по принципу FIFO в холодильнике зелени"],
    actions: [
      "Заказывать зелень на 2–3 дня (в ресторане на Невском это сократило списания на 5,2 тыс ₽/мес)",
      "Маркировка дат вскрытия и FIFO-полка",
    ],
    chart: {
      title: "Списания зелени, ₽ в неделю",
      unit: "₽",
      labels: WEEKS,
      restaurant: [2900, 3400, 3100, 3600, 3300, 3700, 3200, 3500, 3900, 3300, 3400, 3200],
      networkAvg: [1000, 1100, 950, 1050, 1000, 1080, 990, 1020, 1100, 980, 1000, 950],
    },
    status: "new",
  },
  {
    id: "r01-preinventory",
    kind: "problem",
    process: "inventory",
    restaurantId: "R01",
    title: "58% списаний оформлено за 2 дня до инвентаризации",
    effectRubMonth: 9_000,
    effectNote: "оценка скрытых недостач",
    confidence: "medium",
    confidenceNote: "Паттерн повторяется в двух инвентаризациях; сумма — оценка",
    metric: { label: "Доля списаний перед пересчетом", value: "58%", benchmark: "в среднем по сети 14%" },
    summary:
      "Большая часть списаний оформляется 30.09–01.10 и 01.08–03.08, перед пересчетами. Это похоже на «закрытие» недостач списаниями, а не на фактическую порчу.",
    causes: ["Списания не оформляются в момент порчи", "Недостачи закрываются актами перед инвентаризацией"],
    actions: ["Оформлять списание в день порчи с фото", "Еженедельная выборочная инвентаризация ключевых позиций"],
    status: "new",
  },
  // ---------------------------------------------------------------- R01 · opportunities
  {
    id: "r01-margarita-price",
    kind: "opportunity",
    process: "production",
    restaurantId: "R01",
    title: "Пересмотреть цену пиццы «Маргарита»",
    effectRubMonth: 20_700,
    confidence: "medium",
    confidenceNote: "Расчет по марже порции с поправкой на снижение продаж на 5%",
    metric: { label: "Фудкост блюда", value: "36%", benchmark: "целевой 30%" },
    summary:
      "Себестоимость «Маргариты» выросла на 11% за 3 месяца (сыр, томаты), цена в меню не менялась. Блюдо популярное — 1 900 порций в месяц.",
    causes: ["Рост закупочных цен на сыр и томаты", "Цена меню не пересматривалась с марта"],
    actions: ["Поднять цену на 30 ₽ (до 580 ₽)", "Или обновить ТТК: 110 г сыра вместо 125 г"],
    status: "new",
  },
  {
    id: "r01-chicken-price",
    kind: "opportunity",
    process: "purchasing",
    restaurantId: "R01",
    title: "Куриное филе по лучшей цене сети",
    effectRubMonth: 17_700,
    confidence: "high",
    confidenceNote: "Цены сети за 8 недель",
    metric: { label: "Цена за кг", value: "352 ₽", benchmark: "лучшая в сети 318 ₽" },
    summary: "Другой поставщик сети стабильно поставляет филе по 318 ₽/кг. При объеме 520 кг в месяц это 17,7 тыс ₽.",
    causes: [],
    actions: ["Подключить поставщика с лучшей ценой сети", "Сохранить текущего как резервного"],
    status: "in_experiment",
  },
  {
    id: "r01-partial-counts",
    kind: "opportunity",
    process: "inventory",
    restaurantId: "R01",
    title: "Еженедельный пересчет топ-20 позиций",
    effectRubMonth: 12_000,
    effectNote: "за счет раннего выявления потерь",
    confidence: "low",
    confidenceNote: "Оценка; подтвердить экспериментом",
    metric: { label: "Задержка выявления потерь", value: "до 2 месяцев", benchmark: "при пересчете раз в неделю — 7 дней" },
    summary:
      "20 позиций дают 68% себестоимости. Если пересчитывать их раз в неделю, потери вроде перерасхода моцареллы будут видны через неделю, а не через два месяца.",
    causes: [],
    actions: ["Пересчет топ-20 каждый понедельник (около 30 минут)", "Загрузка результата в систему"],
    status: "new",
  },
  // ---------------------------------------------------------------- R02
  {
    id: "r02-beef",
    kind: "problem",
    process: "purchasing",
    restaurantId: "R02",
    title: "Говядина: цена на 11% выше среднего по сети",
    effectRubMonth: 31_000,
    confidence: "high",
    confidenceNote: "Закупки 1С:ERP за 12 недель",
    metric: { label: "Цена за кг", value: "1 140 ₽", benchmark: "в среднем по сети 1 027 ₽" },
    summary: "Говядина (вырезка) закупается у «Мясного ряда» по 1 140 ₽/кг при среднем по сети 1 027 ₽. Объем около 275 кг в месяц.",
    causes: ["Дробные срочные заказы у дорогого поставщика"],
    actions: ["Плановый заказ у основного поставщика сети", "Срочные заказы — только по согласованию"],
    chart: {
      title: "Цена говядины, ₽/кг по неделям",
      unit: "₽",
      labels: WEEKS,
      restaurant: [1090, 1100, 1120, 1120, 1135, 1140, 1140, 1140, 1145, 1140, 1140, 1140],
      networkAvg: [1015, 1018, 1020, 1022, 1025, 1026, 1027, 1027, 1028, 1027, 1027, 1027],
    },
    status: "new",
  },
  {
    id: "r02-chicken-receiving",
    kind: "problem",
    process: "receiving",
    restaurantId: "R02",
    title: "Недостачи курицы в дни поставок",
    effectRubMonth: 8_000,
    confidence: "medium",
    confidenceNote: "Связь с днями поставок выявлена по двум периодам",
    metric: { label: "Количество: ERP vs оприходовано в iiko", value: "−2,4%", benchmark: "в среднем по сети −0,3%" },
    summary: "По накладным ERP закуплено на 2,4% больше курицы, чем оприходовано в iiko. Расхождения приходятся на поставки «ПтицаПром».",
    causes: ["Нет контрольного взвешивания при приемке", "Приемка принимается «по накладной»"],
    actions: ["Взвешивание каждой поставки мяса и птицы", "Акт расхождения при недовесе"],
    status: "in_work",
  },
  {
    id: "r02-mis-sort",
    kind: "problem",
    process: "inventory",
    restaurantId: "R02",
    title: "Пересорт: пармезан и грана падано",
    effectRubMonth: 6_000,
    confidence: "medium",
    confidenceNote: "Две инвентаризации подряд",
    metric: { label: "Излишек / недостача", value: "+7,8 кг / −8,1 кг", benchmark: "суммы почти совпадают" },
    summary: "Излишек одного сыра и недостача другого почти на одну сумму — признак пересорта при учете, а не реальной потери. Но разница в цене создает потерю 6 тыс ₽/мес.",
    causes: ["Сыры хранятся вместе без маркировки", "Списание в iiko идет не по той карточке"],
    actions: ["Раздельное хранение и маркировка", "Проверить привязку в ТТК «Цезаря»"],
    status: "new",
  },
  {
    id: "r02-no-recipes",
    kind: "problem",
    process: "accounting",
    restaurantId: "R02",
    title: "9 продаваемых блюд без ТТК",
    effectRubMonth: null,
    effectNote: "фудкост по 7% выручки не считается",
    confidence: "high",
    confidenceNote: "Сверка продаж r_keeper и ТТК iiko",
    metric: { label: "Выручка без ТТК", value: "7%", benchmark: "в среднем по сети 2%" },
    summary: "Сезонное меню (9 блюд) продается через r_keeper, но в iiko для них нет ТТК. Потери по этим блюдам система не видит.",
    causes: ["Сезонное меню введено без заведения ТТК"],
    actions: ["Завести ТТК для 9 блюд (список в доказательствах)"],
    status: "new",
  },
  {
    id: "r02-menu",
    kind: "opportunity",
    process: "production",
    restaurantId: "R02",
    title: "Меню: продвигать высокомаржинальные пасты",
    effectRubMonth: 22_000,
    confidence: "low",
    confidenceNote: "Оценка по матрице «популярность × маржа»",
    metric: { label: "Маржа пасты", value: "71%", benchmark: "средняя маржа меню 64%" },
    summary: "Три пасты с маржой 71% продаются в 2 раза реже, чем блюда с маржой 55%. Перенос части спроса дает около 22 тыс ₽/мес.",
    causes: [],
    actions: ["Рекомендация официантов", "Позиция «паста дня» в меню"],
    status: "new",
  },
  {
    id: "r02-writeoffs",
    kind: "opportunity",
    process: "writeoffs",
    restaurantId: "R02",
    title: "Списания на уровне среднего по сети",
    effectRubMonth: 9_000,
    confidence: "medium",
    confidenceNote: "12 недель актов списания",
    metric: { label: "Списания", value: "1,9% выручки", benchmark: "в среднем по сети 1,7%" },
    summary: "Списания выше среднего по сети на 0,2 пункта — в основном выпечка и молочка.",
    causes: [],
    actions: ["Корректировать заказ выпечки по дням недели"],
    status: "new",
  },
  {
    id: "r02-cream",
    kind: "opportunity",
    process: "purchasing",
    restaurantId: "R02",
    title: "Сливки по лучшей цене сети",
    effectRubMonth: 6_500,
    confidence: "high",
    confidenceNote: "Цены сети за 8 недель",
    metric: { label: "Цена за литр", value: "368 ₽", benchmark: "лучшая в сети 352 ₽" },
    summary: "Перевод закупки сливок на поставщика с лучшей ценой сети дает 6,5 тыс ₽/мес.",
    causes: [],
    actions: ["Подключить поставщика с лучшей ценой сети"],
    status: "new",
  },
  // ---------------------------------------------------------------- R03
  {
    id: "r03-salmon",
    kind: "problem",
    process: "production",
    restaurantId: "R03",
    title: "Перерасход лосося по ТТК",
    effectRubMonth: 27_000,
    confidence: "high",
    confidenceNote: "Две полные инвентаризации",
    metric: { label: "Расход сверх ТТК", value: "6,8%", benchmark: "в среднем по сети 2,9%", norm: "норма до 2%" },
    summary: "Фактический расход лосося на 6,8% выше ТТК. Основная доля — разделка целой рыбы.",
    causes: ["Выход филе при разделке ниже, чем заложено в ТТК (52% против 58%)"],
    actions: ["Проверить выход при разделке на 3 поставках", "Если выход ниже — обновить ТТК или сменить поставщика"],
    chart: {
      title: "Расход сверх ТТК по периодам между инвентаризациями",
      unit: "%",
      labels: INVENTORY_PERIODS,
      restaurant: [5.9, 6.4, 6.8],
      networkAvg: [2.7, 2.8, 2.9],
      norm: 2,
      normLabel: "Норма 2%",
    },
    status: "new",
  },
  {
    id: "r03-bread",
    kind: "problem",
    process: "writeoffs",
    restaurantId: "R03",
    title: "Списания хлеба выше среднего по сети",
    effectRubMonth: 7_000,
    confidence: "high",
    confidenceNote: "Акты списания за 12 недель",
    metric: { label: "Списания хлеба", value: "9% закупки", benchmark: "в среднем по сети 4%" },
    summary: "Хлеб и чиабатта списываются в понедельник и вторник — заказ не учитывает спад продаж в начале недели.",
    causes: ["Одинаковый заказ на все дни недели"],
    actions: ["Заказ по дням недели на основе продаж"],
    status: "new",
  },
  {
    id: "r03-erp-gap",
    kind: "problem",
    process: "accounting",
    restaurantId: "R03",
    title: "Закупки из 1С:ERP загружены только по 11.10",
    effectRubMonth: null,
    effectNote: "цены за неделю не проверены",
    confidence: "high",
    confidenceNote: "Свежесть данных",
    metric: { label: "Отставание данных", value: "7 дней", benchmark: "по другим ресторанам — 1 день" },
    summary: "Последняя выгрузка закупок из ERP — 11.10. Контроль цен за последнюю неделю не выполнен.",
    causes: [],
    actions: ["Загрузить выгрузку закупок 1С:ERP за 12–18.10"],
    status: "new",
  },
  {
    id: "r03-caesar-price",
    kind: "opportunity",
    process: "production",
    restaurantId: "R03",
    title: "Пересмотреть цену салата «Цезарь»",
    effectRubMonth: 18_000,
    confidence: "medium",
    confidenceNote: "С поправкой на снижение продаж на 5%",
    metric: { label: "Фудкост блюда", value: "34%", benchmark: "целевой 30%" },
    summary: "Себестоимость «Цезаря» выросла на 9% (курица, пармезан), цена не менялась.",
    causes: [],
    actions: ["Поднять цену на 30 ₽"],
    status: "new",
  },
  {
    id: "r03-vegetables",
    kind: "opportunity",
    process: "purchasing",
    restaurantId: "R03",
    title: "Овощи по лучшей цене сети",
    effectRubMonth: 11_000,
    confidence: "high",
    confidenceNote: "Цены сети за 8 недель",
    metric: { label: "Корзина овощей", value: "+8%", benchmark: "к лучшей цене сети" },
    summary: "Томаты, огурцы и перец закупаются на 8% дороже лучшей цены сети.",
    causes: [],
    actions: ["Перейти к поставщику овощей сети"],
    status: "new",
  },
  {
    id: "r03-greens-batch",
    kind: "opportunity",
    process: "storage",
    restaurantId: "R03",
    title: "Закрепить малые партии зелени",
    effectRubMonth: 5_200,
    effectNote: "подтверждено экспериментом",
    confidence: "high",
    confidenceNote: "Эксперимент завершен 10.10",
    metric: { label: "Списания зелени", value: "−48%", benchmark: "к периоду до эксперимента" },
    summary: "Эксперимент с заказом зелени на 2–3 дня подтвердил снижение списаний. Осталось закрепить в регламенте.",
    causes: [],
    actions: ["Внести правило в регламент заказа"],
    status: "resolved",
  },
  // ---------------------------------------------------------------- network-wide (HQ only)
  {
    id: "net-fries-recipe",
    kind: "problem",
    process: "accounting",
    restaurantId: null,
    title: "ТТК картофеля фри, вероятно, устарела",
    effectRubMonth: null,
    effectNote: "искажает фудкост сети на 0,4 пункта",
    confidence: "medium",
    confidenceNote: "Одинаковое отклонение во всех трех ресторанах",
    metric: { label: "Расход сверх ТТК", value: "6,1–6,6%", benchmark: "во всех ресторанах" },
    summary:
      "Все три ресторана показывают одинаковый перерасход картофеля фри. Когда отклонение одинаковое во всей сети, вероятнее ошибка в ТТК (выход после жарки), а не нарушение на кухнях.",
    causes: ["Выход после обжарки в ТТК 85%, фактический по замерам поставщика — 79%"],
    actions: ["Провести контрольную обжарку и обновить ТТК во всех ресторанах"],
    status: "new",
  },
];

export const KPIS: Record<string, Kpis> = {
  R01: { foodCostActual: 32.4, foodCostTheoretical: 29.8, writeoffsPct: 2.6, overpayRubMonth: 21_000 },
  R02: { foodCostActual: 31.1, foodCostTheoretical: 29.5, writeoffsPct: 1.9, overpayRubMonth: 31_000 },
  R03: { foodCostActual: 30.2, foodCostTheoretical: 29.1, writeoffsPct: 1.7, overpayRubMonth: 11_000 },
};

export const DIGEST_TEXT: Record<string, string> = {
  R01:
    "Главная потеря — перерасход моцареллы: 38 тыс ₽ в месяц, и он растет третий период подряд. Контрольное взвешивание уже идет — первые результаты будут после пересчета 27.10. Быстрые деньги — в закупке: сливки и куриное филе можно брать дешевле, это вместе около 39 тыс ₽ в месяц.",
  R02:
    "Основные потери в закупке: говядина на 11% дороже среднего по сети. Важно завести ТТК для сезонных блюд — сейчас по 7% выручки фудкост не считается.",
  R03:
    "Ресторан стабилен, но лосось расходуется на 6,8% больше ТТК — проверьте выход при разделке. Загрузите закупки из ERP за последнюю неделю.",
};

export const STOCK_RISKS: StockRisk[] = [
  { restaurantId: "R01", product: "Моцарелла", daysLeft: 2, nextDeliveryInDays: 4, supplier: "Сырный дом" },
  { restaurantId: "R01", product: "Руккола", daysLeft: 3, nextDeliveryInDays: 3, supplier: "Зелень Экспресс" },
  { restaurantId: "R02", product: "Говяжья вырезка", daysLeft: 1, nextDeliveryInDays: 2, supplier: "Мясной ряд" },
  { restaurantId: "R03", product: "Лосось охлажденный", daysLeft: 2, nextDeliveryInDays: 2, supplier: "Северная рыба" },
];

export const IMPROVEMENTS: Improvement[] = [
  { restaurantId: "R01", text: "Списания хлеба −32% к прошлой неделе" },
  { restaurantId: "R01", text: "Все накладные недели загружены без ошибок" },
  { restaurantId: "R02", text: "Приемка: взвешивание введено на 3 из 5 поставок" },
  { restaurantId: "R03", text: "Списания зелени −48% после эксперимента с малыми партиями" },
];

export const TASKS: Task[] = [
  {
    id: "t1",
    restaurantId: "R01",
    title: "Контрольное взвешивание моцареллы на раздаче",
    source: "Эксперимент «Контрольное взвешивание сыра»",
    findingId: "r01-mozzarella",
    experimentId: "e-mozzarella",
    due: "10.11",
    status: "in_progress",
    checklist: ["Весы на станции пиццы", "Фото-стандарт порции у станции", "Пересчет моцареллы каждый понедельник"],
  },
  {
    id: "t2",
    restaurantId: "R01",
    title: "Запросить у «Молочного двора» цену на сливки",
    source: "Взято директором из сводки",
    findingId: "r01-cream",
    due: "25.10",
    status: "assigned",
  },
  {
    id: "t3",
    restaurantId: "R02",
    title: "Взвешивать каждую поставку мяса и птицы",
    source: "Взято директором из сводки",
    findingId: "r02-chicken-receiving",
    due: "20.10",
    status: "overdue",
  },
  {
    id: "t4",
    restaurantId: "R03",
    title: "Заказывать зелень партиями на 2–3 дня",
    source: "Эксперимент «Малые партии зелени»",
    experimentId: "e-greens",
    due: "10.10",
    status: "done",
    report: "Заказ переведен на вторник и пятницу. Списания за 4 недели — 5 600 ₽ против 10 800 ₽ раньше.",
    result: "Подтверждено проверкой: +5,2 тыс ₽ в месяц",
  },
];

export const EXPERIMENTS: Experiment[] = [
  {
    id: "e-chicken",
    title: "Куриное филе по лучшей цене сети",
    hypothesis:
      "Если рестораны на Тверской и на Арбате перейдут на поставщика филе с лучшей ценой сети, затраты на филе снизятся на 9–10% без потери качества.",
    findingId: "r01-chicken-price",
    design: "Ресторан против ресторана: тест — R01, R02; контроль — R03",
    test: ["R01", "R02"],
    control: ["R03"],
    metric: "Цена филе, ₽/кг, и жалобы гостей на блюда с курицей",
    baseline: "8 недель до старта",
    period: "4 недели, с 27.10",
    expectedRubMonth: 28_000,
    status: "proposed",
  },
  {
    id: "e-mozzarella",
    title: "Контрольное взвешивание сыра",
    hypothesis: "Если две недели взвешивать моцареллу на раздаче, перерасход по ТТК снизится с 9% до 3%.",
    findingId: "r01-mozzarella",
    design: "Контроль внутри ресторана: моцарелла (тест) против остальных сыров (контроль)",
    test: ["R01"],
    control: [],
    metric: "Расход сверх ТТК, % (еженедельный пересчет моцареллы)",
    baseline: "Период 03.08–01.10",
    period: "13.10 – 10.11",
    expectedRubMonth: 25_500,
    status: "running",
    progress: "Неделя 1 из 4: перерасход по пересчету 20.10 — 4,1% (было 9,1%). Промежуточный результат, вывод — после 10.11.",
  },
  {
    id: "e-greens",
    title: "Малые партии зелени",
    hypothesis: "Если заказывать зелень на 2–3 дня вместо 5–6, списания снизятся без дефицитов.",
    design: "Ресторан против ресторанов: тест — R03; контроль — R01, R02",
    test: ["R03"],
    control: ["R01", "R02"],
    metric: "Списания зелени, ₽ в неделю; дни дефицита",
    baseline: "8 недель до старта",
    period: "15.09 – 10.10",
    expectedRubMonth: 4_000,
    status: "completed",
    result: {
      verdict: "confirmed",
      effectRubMonth: 5_200,
      ciLow: 3_100,
      ciHigh: 7_300,
      text: "Списания зелени снизились на 48% относительно контрольных ресторанов (разница разниц). Дефицитов не было.",
      rolloutRubMonth: 10_000,
    },
  },
];

export const FRESHNESS: DataSourceFreshness[] = RESTAURANTS.flatMap((r) => [
  { restaurantId: r.id, source: "r_keeper", dataset: "Продажи", lastDate: "18.10", status: "good" },
  {
    restaurantId: r.id,
    source: "iiko",
    dataset: "Склад и ТТК",
    lastDate: "18.10",
    status: "good",
    note: `инвентаризация ${PERIOD.lastInventory.slice(0, 5)}`,
  },
  r.id === "R03"
    ? { restaurantId: r.id, source: "erp", dataset: "Закупки", lastDate: "11.10", status: "warning", note: "отставание 7 дней" }
    : { restaurantId: r.id, source: "erp", dataset: "Закупки", lastDate: "17.10", status: "good" },
] as DataSourceFreshness[]);

// ---------------------------------------------------------------- To-Be: plain-language layer
// Conclusions, scales and balances for each finding (docs/ux/03-to-be.md). Kept separate so the
// base findings stay close to what the analytics engine computes.

type FindingExtras = Pick<Finding, "headline" | "scale" | "composition" | "dispute"> & { chartConclusion?: string };

const EXTRAS: Record<string, FindingExtras> = {
  "r01-mozzarella": {
    headline: "Моцареллы уходит на 9% больше нормы — 84 кг за два месяца, и перерасход растет третий период подряд.",
    scale: { label: "Расход сверх нормы", unit: "%", me: 9.1, network: 3.4, norm: 2, lowerIsBetter: true },
    composition: {
      unit: "кг",
      formula: "Было 38 кг + пришло 1 012 кг − осталось 43 кг = израсходовано 1 007 кг",
      parts: [
        { label: "по техкартам проданных блюд", value: 920, tone: "brand" },
        { label: "списано по актам", value: 3, tone: "neutral" },
        { label: "не объяснено — это потеря", value: 84, tone: "loss" },
      ],
    },
    chartConclusion: "Перерасход растет третий период подряд, а в среднем по сети держится около 3%.",
  },
  "r01-cream": {
    headline: "Сливки обходятся на 51 ₽ за литр дороже, чем в среднем по сети: в августе поставщик поднял цену, и ее никто не пересмотрел.",
    scale: { label: "Цена за литр", unit: "₽", me: 412, network: 361, lowerIsBetter: true },
    chartConclusion: "С августа цена выросла на 13% и не снижалась; в сети цена стабильна.",
  },
  "r01-greens": {
    headline: "Зелени списываем в 3,3 раза больше, чем в среднем по сети: заказываем на 5–6 дней, а хранится она 3 дня.",
    scale: { label: "Списания зелени в неделю", unit: "₽", me: 3375, network: 1018, lowerIsBetter: true },
    chartConclusion: "Каждую неделю списываем около 3,4 тыс ₽ зелени — в сети около 1 тыс ₽.",
  },
  "r01-preinventory": {
    headline: "Больше половины списаний оформляется за 2 дня до инвентаризации. Так обычно закрывают недостачи, а не реальную порчу.",
    scale: { label: "Доля списаний перед пересчетом", unit: "%", me: 58, network: 14, lowerIsBetter: true },
  },
  "r01-margarita-price": {
    headline: "Себестоимость «Маргариты» выросла на 11%, а цена в меню прежняя — каждая пицца приносит меньше.",
    scale: { label: "Фудкост блюда", unit: "%", me: 36, norm: 30, lowerIsBetter: true },
  },
  "r01-chicken-price": {
    headline: "Другой поставщик сети возит такое же филе на 34 ₽ за кг дешевле.",
    scale: { label: "Цена за кг", unit: "₽", me: 352, network: 318, networkLabel: "Лучшая в сети", lowerIsBetter: true },
  },
  "r01-partial-counts": {
    headline: "Если раз в неделю пересчитывать 20 самых дорогих позиций, потери будут видны через неделю, а не через два месяца.",
  },
  "r02-beef": {
    headline: "Говядину берем на 113 ₽ за кг дороже среднего по сети — из-за срочных заказов у дорогого поставщика.",
    scale: { label: "Цена за кг", unit: "₽", me: 1140, network: 1027, lowerIsBetter: true },
    chartConclusion: "Цена растет с конца июля; в сети почти не меняется.",
  },
  "r02-chicken-receiving": {
    headline: "По накладным 1С приходит на 2,4% больше курицы, чем оприходуется в iiko. Похоже на недовес при приемке.",
    scale: { label: "Расхождение 1С и iiko", unit: "%", me: 2.4, network: 0.3, lowerIsBetter: true },
  },
  "r02-mis-sort": {
    headline: "Пармезан и грана падано путают при учете: излишек одного почти равен недостаче другого.",
    dispute: {
      by: "Директор, Ресторан на Арбате",
      reason: "Причина другая",
      comment: "Сыры хранятся раздельно и подписаны. Проверьте, не стоит ли в техкарте «Цезаря» грана вместо пармезана.",
      date: "21.10",
    },
  },
  "r02-no-recipes": {
    headline: "У 9 блюд сезонного меню нет техкарт — по ним система не видит потери (7% выручки).",
    scale: { label: "Выручка без техкарт", unit: "%", me: 7, network: 2, lowerIsBetter: true },
  },
  "r02-menu": { headline: "Три пасты с высокой наценкой продаются в 2 раза реже, чем менее выгодные блюда." },
  "r02-writeoffs": {
    headline: "Списания чуть выше среднего по сети — в основном выпечка и молочка.",
    scale: { label: "Списания, % выручки", unit: "%", me: 1.9, network: 1.7, lowerIsBetter: true },
  },
  "r02-cream": {
    headline: "Сливки можно брать на 16 ₽ за литр дешевле у поставщика сети.",
    scale: { label: "Цена за литр", unit: "₽", me: 368, network: 352, networkLabel: "Лучшая в сети", lowerIsBetter: true },
  },
  "r03-salmon": {
    headline: "Лосося уходит на 6,8% больше нормы: при разделке получаем 52% филе, а в техкарте заложено 58%.",
    scale: { label: "Расход сверх нормы", unit: "%", me: 6.8, network: 2.9, norm: 2, lowerIsBetter: true },
    chartConclusion: "Перерасход держится выше 6% три периода подряд — проблема постоянная, а не случайная.",
  },
  "r03-bread": {
    headline: "Хлеб заказываем одинаково на все дни, а в понедельник и вторник продаем меньше — остаток списываем.",
    scale: { label: "Списания хлеба, % закупки", unit: "%", me: 9, network: 4, lowerIsBetter: true },
  },
  "r03-erp-gap": { headline: "Закупки из 1С загружены только по 11.10 — цены за последнюю неделю не проверены." },
  "r03-caesar-price": {
    headline: "Себестоимость «Цезаря» выросла на 9%, а цена в меню прежняя.",
    scale: { label: "Фудкост блюда", unit: "%", me: 34, norm: 30, lowerIsBetter: true },
  },
  "r03-vegetables": { headline: "Томаты, огурцы и перец берем на 8% дороже лучшей цены сети." },
  "r03-greens-batch": { headline: "Малые партии зелени сократили списания почти вдвое — осталось закрепить правило." },
  "net-fries-recipe": {
    headline: "Во всех трех ресторанах картофеля фри уходит на 6% больше нормы — скорее всего, ошибка в техкарте, а не на кухнях.",
  },
};

for (const f of FINDINGS) {
  const extra = EXTRAS[f.id];
  if (!extra) continue;
  const { chartConclusion, ...rest } = extra;
  Object.assign(f, rest);
  if (chartConclusion && f.chart) f.chart.conclusion = chartConclusion;
  if (rest.dispute) f.status = "disputed";
}

/** Weekly network trend for HQ: what can still be returned vs what is confirmed as returned (₽/month). */
export const NETWORK_TREND: WeeklyTrend = {
  labels: ["24.08", "31.08", "07.09", "14.09", "21.09", "28.09", "05.10", "12.10"],
  onTable: [331_000, 322_000, 318_000, 309_000, 301_000, 294_000, 286_000, 0],
  returned: [0, 0, 0, 1_200, 2_600, 4_100, 5_200, 5_200],
};

/** Losses one week earlier, for "better / worse than last week". */
export const LOSSES_LAST_WEEK: Record<string, number> = { R01: 86_000, R02: 41_000, R03: 34_000 };

/** "Can be returned" per restaurant one week earlier, for the director's hero. */
export const ON_TABLE_LAST_WEEK: Record<string, number> = { R01: 141_000, R02: 89_000, R03: 72_000 };
