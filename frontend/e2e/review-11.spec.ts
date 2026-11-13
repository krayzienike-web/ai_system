// Code review of stage 11 (docs/reviews/2026-11-13-stage-11-review.md): the fixes that are words and buttons.
import { expect, test } from "@playwright/test";

import { open, signIn, signInAs } from "./helpers";

test("TC-UI-44: «Напомнить» names its task and is done for today once pressed", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await page.getByRole("link", { name: "Задачи сети" }).first().click();
  const remind = page.getByRole("button", { name: /^Напомнить: Проверить выход филе при разделке/ });
  await remind.click();
  await expect(page.getByText("Директору отправлено напоминание")).toBeVisible();
  const done = page.getByRole("button", { name: /^Напомнили сегодня: Проверить выход филе/ });
  await expect(done).toBeDisabled();
});

test("TC-UI-43: who cannot set units opens the file's report instead", async ({ page }) => {
  await signInAs(page, "analyst@demo.local");
  await open(page, /^Данные/);
  const row = page.locator("li", { hasText: "Приходы 1С R03 19.10.csv" });
  await expect(row.getByRole("button", { name: "Задать единицы" })).toHaveCount(0);
  await row.getByRole("button", { name: "Открыть отчет" }).click();
  await expect(page.getByText("Коэффициенты задает администратор управляющей компании")).toBeVisible();
});
