// Navigation for the whole MVP; sections not built yet show which roadmap stage delivers them.
export interface Section {
  path: string;
  title: string;
  stage?: string;
  description: string;
}

export const SECTIONS: Section[] = [
  { path: "/", title: "Главная", description: "Обзор ресторана или сети" },
  {
    path: "/digest",
    title: "AI-сводка",
    stage: "этап 6",
    description: "Карта процессов, 3–5 проблем и 3–5 возможностей с оценкой в ₽/мес",
  },
  {
    path: "/insights",
    title: "Инсайты",
    stage: "этапы 3–4",
    description: "Находки AI-менеджера запасов: ТТК, фудкост, цены, инвентаризации, списания",
  },
  {
    path: "/chat",
    title: "Чат с ассистентом",
    stage: "этап 5",
    description: "Вопросы к данным на естественном языке",
  },
  {
    path: "/experiments",
    title: "Эксперименты",
    stage: "этап 7",
    description: "Гипотезы, тестовые и контрольные группы, замер эффекта",
  },
  { path: "/tasks", title: "Задачи", stage: "этап 7", description: "Задачи директорам и их исполнение" },
  {
    path: "/import",
    title: "Загрузка данных",
    stage: "этап 2",
    description: "Выгрузки r_keeper, iiko и 1С:ERP в XLS/CSV",
  },
  { path: "/restaurants", title: "Рестораны", description: "Рестораны сети" },
];
