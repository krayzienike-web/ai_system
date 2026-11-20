// TC-UI-38 (docs/13-testing.md): «Помощник» on the home screen (stage 9, ADR 0010). The director takes the list
// «что пересчитать внимательно» into work — it becomes a task with the list; the HQ admin moves a stuck task's
// deadline. What the notes say is the server's (the prototype replays it).
import { expect, type Locator, test } from "@playwright/test";

import { open, signIn, signInAs } from "./helpers";

/** The home screen shows the first notes only; the HQ's list is longer — open all of it. */
async function showAll(assistant: Locator) {
  await assistant.getByRole("button", { name: /^Показать еще/ }).click();
}

test("TC-UI-38: the director takes the inventory list into work", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  const assistant = page.getByRole("region", { name: "Помощник" });
  const note = assistant.getByRole("listitem").filter({ hasText: "что пересчитать внимательно" });
  await expect(note).toBeVisible();
  await expect(note.getByText(/по нему открыта находка/).first()).toBeVisible();
  await note.getByRole("button", { name: "Создать задачу" }).click();
  await expect(page.getByText("Задача создана — она в «Задачах»")).toBeVisible();
  await expect(note).toHaveCount(0);
  await open(page, /Задачи/);
  await expect(page.getByText(/Подготовка к инвентаризации/).first()).toBeVisible();
});

test("TC-UI-38: the HQ admin moves a stuck task's deadline", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  const assistant = page.getByRole("region", { name: "Помощник" });
  await showAll(assistant);
  const stuck = assistant.getByRole("listitem").filter({ hasText: "просрочена и не начата" });
  await expect(stuck).toBeVisible();
  await stuck.getByRole("button", { name: /Перенести на/ }).click();
  await expect(page.getByText(/Срок перенесен на/)).toBeVisible();
  await expect(stuck).toHaveCount(0);
});

test("TC-UI-38: the HQ analyst reads the notes but has no buttons to answer them", async ({ page }) => {
  await signInAs(page, "analyst@demo.local");
  const assistant = page.getByRole("region", { name: "Помощник" });
  await showAll(assistant);
  await expect(assistant.getByRole("listitem").filter({ hasText: "просрочена и не начата" })).toBeVisible();
  for (const name of [/Перенести на/, "Создать задачу", "Поставить задачи", "Отметить: отправлено", "Не нужно", "Скрыть"])
    await expect(assistant.getByRole("button", { name })).toHaveCount(0);
});

// TC-UI-42 (stage 10): the HQ's own notes — a transfer becomes two tasks, the director sees none of the notes.
// TC-UI-44 (Q39): both tasks are in the HQ's «Задачи сети», under «Без находки».
test("TC-UI-42: the HQ admin sets the tasks of a transfer; the director does not see the HQ's notes", async ({
  page,
}) => {
  await signIn(page, "Управляющая компания");
  const assistant = page.getByRole("region", { name: "Помощник" });
  await showAll(assistant);
  const move = assistant.getByRole("listitem").filter({ hasText: "Перемещение:" }).first();
  await expect(move.getByText("Будут поставлены задачи:")).toBeVisible();
  await expect(assistant.getByText("Вся сеть").first()).toBeVisible(); // the agenda and the supplier request
  await move.getByRole("button", { name: "Поставить задачи" }).click();
  await expect(page.getByText("директора обоих ресторанов увидят их в «Задачах»")).toBeVisible();
  await expect(move).toHaveCount(0);

  await page.getByRole("link", { name: "Задачи сети" }).first().click();
  await expect(page.getByRole("heading", { name: "Задачи сети" })).toBeVisible();
  await page.getByRole("group", { name: "Какие задачи" }).getByRole("button", { name: /Без находки/ }).click();
  const rows = page.getByRole("listitem");
  await expect(rows.filter({ hasText: "Передать в «Ресторан на Покровке»" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Принять из «Ресторан на Арбате»" })).toHaveCount(1);
  await page.getByLabel("Ресторан").selectOption({ label: "Ресторан на Арбате" });
  await expect(rows.filter({ hasText: "Принять из" })).toHaveCount(0); // that one is R04's
});

test("TC-UI-42: the director's «Помощник» has none of the HQ's notes", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  const assistant = page.getByRole("region", { name: "Помощник" });
  await expect(assistant).toBeVisible();
  for (const text of ["Перемещение:", "Повестка планерки", "Недостача:", "Запрос «"])
    await expect(assistant.getByText(text)).toHaveCount(0);
});

// TC-UI-48 (stage 12): the count's result — the director sees the task's points before pressing and makes it;
// the HQ gets the network's summary and the note about menu prices to copy, with a link to «Меню».
test("TC-UI-48: the director explains the count's result in a task", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  const assistant = page.getByRole("region", { name: "Помощник" });
  const note = assistant.getByRole("listitem").filter({ hasText: "Итоги инвентаризации 01.10" });
  await expect(note.getByText("В задаче будут пункты:")).toBeVisible();
  await expect(note.getByText(/^Объяснить: Сыр Моцарелла/)).toBeVisible();
  await expect(note.getByRole("link", { name: "Открыть находки" })).toBeVisible();
  await note.getByRole("button", { name: "Создать задачу" }).click();
  await expect(page.getByText("Задача создана — она в «Задачах»")).toBeVisible();
  await open(page, /Задачи/);
  await expect(page.getByText(/Объяснить расхождения инвентаризации 01\.10/).first()).toBeVisible();
});

test("TC-UI-48: the HQ gets the network's summary and menu prices", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  const assistant = page.getByRole("region", { name: "Помощник" });
  await showAll(assistant);
  const summary = assistant.getByRole("listitem").filter({ hasText: "Итоги инвентаризаций" });
  await expect(summary).toHaveCount(1);
  await expect(summary.getByRole("button", { name: "Скрыть" })).toBeVisible();
  await expect(assistant.getByText("Итоги инвентаризации 01.10")).toHaveCount(0); // the directors' own
  const menu = assistant.getByRole("listitem").filter({ hasText: "Цены меню:" });
  await expect(menu.getByText(/Лосось на гриле/)).toBeVisible();
  await expect(menu.getByRole("button", { name: "Скопировать записку" })).toBeVisible();
  await menu.getByRole("link", { name: "Открыть меню" }).click();
  await expect(page.getByRole("heading", { name: "Меню: популярность и маржа" })).toBeVisible();
});

// TC-UI-49 (UX pass 20.11.2026): the main numbers come first; «Помощник» is right under them and shows three notes,
// the rest behind «Показать еще N» — the HQ's long list does not push the network's money off the screen.
test("TC-UI-49: the HQ home shows its numbers before the assistant's first three notes", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  const assistant = page.getByRole("region", { name: "Помощник" });
  const notes = assistant.locator(":scope > ul > li"); // the notes, not the lines inside them
  await expect(notes).toHaveCount(3);
  const hero = page.getByText("Найденный потенциал прибыли").first();
  await expect(hero).toBeInViewport();
  const [heroY, assistantY] = await Promise.all([hero.boundingBox(), assistant.boundingBox()]);
  expect(heroY!.y).toBeLessThan(assistantY!.y);
  const more = assistant.getByRole("button", { name: /^Показать еще \d+ сообщени/ });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.click();
  expect(await notes.count()).toBeGreaterThan(3);
  await assistant.getByRole("button", { name: "Свернуть" }).click();
  await expect(notes).toHaveCount(3);
});

test("TC-UI-49: the director's week starts with the restaurant's money, then «Помощник»", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  await expect(page.getByText("Найденный потенциал прибыли").first()).toBeInViewport();
  const assistant = page.getByRole("region", { name: "Помощник" });
  await expect(assistant).toBeVisible();
  await expect(assistant.getByRole("button", { name: /^Показать еще/ })).toHaveCount(0); // two notes only
});
