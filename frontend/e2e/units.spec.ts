// TC-UI-43 (docs/13-testing.md): a 1С file stopped by unknown units — the HQ sets the factors on the file's
// report and checks it again, with no new upload (Q35).
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

test("TC-UI-43: the HQ sets the units of a failed 1С file and loads it", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /^Данные/);
  const row = page.locator("li", { hasText: "Приходы 1С R03 19.10.csv" });
  await row.getByRole("button", { name: "Задать единицы" }).click();

  await expect(page.getByText("Сколько это в базовых единицах?")).toBeVisible();
  const again = page.getByRole("button", { name: "Проверить заново" });
  await page.getByRole("textbox", { name: "Сколько л в 1 «упак» товара «Сливки 33%»" }).fill("1");
  await page.getByRole("button", { name: "Сохранить: Сколько л в 1 «упак» товара «Сливки 33%»" }).click();
  await again.click();
  await expect(page.getByText("Проверили: у части единиц все еще нет коэффициента")).toBeVisible();

  await page.getByRole("textbox", { name: "Сколько л в 1 «бут» товара «Масло оливковое»" }).fill("0,5");
  await page.getByRole("button", { name: "Сохранить: Сколько л в 1 «бут» товара «Масло оливковое»" }).click();
  await again.click();
  await expect(page.getByText("Файл проходит проверку — его можно загрузить")).toBeVisible();
  await expect(page.getByText("Сколько это в базовых единицах?")).toBeHidden();
});
