// TC-UI-03 (docs/13-testing.md): engine parameters per module, validated before saving.
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

test("TC-UI-03: an out-of-range value is explained and cannot be saved; «вернуть» keeps other edits", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Нормы и настройки/);
  await page.getByText("M3 · Закупочные цены").click();

  const overpay = page.getByLabel("Насколько дороже типичной цены сети");
  const save = page.getByRole("button", { name: /Сохранить параметры/ });
  await overpay.fill("500");
  await expect(page.getByText(/^от \d+ до \d+$/).first()).toBeVisible();
  await expect(save).toBeDisabled();

  await overpay.fill("7");
  await expect(save).toHaveText(/\(1\)/);
  await save.click();
  await expect(page.getByText("своих значений: 1")).toBeVisible();

  // An edit elsewhere, then «вернуть» on the saved one: both stay as unsaved edits.
  const window = page.getByLabel("Окно сравнения цен ресторанов");
  await window.fill("28");
  await page.locator("li", { has: overpay }).getByRole("button", { name: /вернуть/ }).click();
  await expect(window).toHaveValue("28");
  await expect(save).toHaveText(/\(2\)/);
  await save.click();
  await expect(page.getByText("своих значений: 1")).toBeVisible(); // only the window is own now
});
