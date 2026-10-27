// TC-UI-06 (docs/13-testing.md): the director reports a task done in «Мои задачи»; it moves to «Сделано»
// with the result to be measured after the next inventory count.
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

test("TC-UI-06: the director reports a task done", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  await open(page, /Задачи/);
  const ready = page.getByRole("button", { name: "Готово" });
  await expect(ready.first()).toBeVisible();
  const before = await ready.count();

  await ready.first().click();
  await page.getByLabel("Отчет о выполнении").fill("Перевесили порции, обучили смену");
  await page.getByRole("button", { name: "Отметить сделанной" }).click();
  await expect(page.getByText(/Отчет отправлен/)).toBeVisible();
  await expect(ready).toHaveCount(before - 1);
  await expect(page.getByText("Отчет: Перевесили порции, обучили смену").or(page.getByText(/Перевесили порции/)).first()).toBeVisible();
});
