// TC-UI-12 (docs/14-demo-scenario.md): the 10-minute demo, end to end, on the prototype build.
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

test("TC-UI-12: the demo scenario goes through by clicks", async ({ page }) => {
  // HQ: the money on the table and where it is.
  await signIn(page, "Управляющая компания");
  await expect(page.getByText("Найденный потенциал прибыли").first()).toBeVisible();
  await expect(page.getByText("Переплаты поставщикам")).toBeVisible();
  await expect(page.getByText("Цена выросла по всей сети: Лосось охлажденный")).toBeVisible();

  // Restaurants × processes → the finding → down to the invoices.
  await page.getByRole("button", { name: /на Тверской, Производство/ }).click();
  await page.getByRole("link", { name: /Перерасход по техкарте: Сыр Моцарелла/ }).first().click();
  await expect(page.getByText("Это много?")).toBeVisible();
  await expect(page.getByText("Из чего сложилась потеря?")).toBeVisible();
  await page.getByRole("button", { name: /Документы/ }).click();
  await expect(page.getByRole("table").last()).toContainText("Накладная");

  // The review: a new engine finding, checked against the data, confirmed.
  await open(page, /Проверка находок/);
  await page.getByRole("link", { name: /Закончится до поставки: Паста спагетти/ }).click();
  await expect(page.getByText("Расчет по шагам")).toBeVisible();
  await page.getByRole("button", { name: /Подтвердить/ }).click();
  await expect(page.getByLabel("Путь находки")).toContainText("Проверено");

  // Decisions and the head's report.
  await open(page, /Ждут решения/);
  await expect(page.getByRole("heading", { name: /Проверки к запуску/ })).toBeVisible();
  await open(page, /Отчет для руководителя/);
  await expect(page.getByText("Подтвержденный эффект").first()).toBeVisible();

  // The director: their week and a task done with a report.
  await page.getByRole("button", { name: "Выйти" }).first().click();
  await signIn(page, "Директор ресторана");
  await expect(page.getByText("Найденный потенциал прибыли").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Проверка находок/ })).toHaveCount(0);
  await open(page, /Задачи/);
  await page.getByRole("button", { name: "Готово" }).first().click();
  await page.getByLabel("Отчет о выполнении").fill("Взвесили порции, обучили смену");
  await page.getByRole("button", { name: "Отметить сделанной" }).click();
  await expect(page.getByText(/Отчет отправлен/)).toBeVisible();
});
