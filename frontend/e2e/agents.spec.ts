// TC-UI-38 (docs/13-testing.md): «Помощник» on the home screen (stage 9, ADR 0010). The director takes the list
// «что пересчитать внимательно» into work — it becomes a task with the list; the HQ admin moves a stuck task's
// deadline. What the notes say is the server's (the prototype replays it).
import { expect, test } from "@playwright/test";

import { open, signIn, signInAs } from "./helpers";

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
  const stuck = assistant.getByRole("listitem").filter({ hasText: "просрочена и не начата" });
  await expect(stuck).toBeVisible();
  await stuck.getByRole("button", { name: /Перенести на/ }).click();
  await expect(page.getByText(/Срок перенесен на/)).toBeVisible();
  await expect(stuck).toHaveCount(0);
});

test("TC-UI-38: the HQ analyst reads the notes but has no buttons to answer them", async ({ page }) => {
  await signInAs(page, "analyst@demo.local");
  const assistant = page.getByRole("region", { name: "Помощник" });
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
