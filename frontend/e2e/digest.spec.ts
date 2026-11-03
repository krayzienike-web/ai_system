// TC-UI-18, TC-UI-19 (docs/13-testing.md): the weekly digest (stage 6) — a director reads theirs and says
// «Не согласен» with a reason, which the HQ then sees; the HQ switches between the network and a restaurant.
import { expect, test } from "@playwright/test";

import { expectNoOverflow, open, signIn } from "./helpers";

test("TC-UI-18: the director disagrees with an item, the reason reaches the HQ", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  await open(page, /Сводка/);
  await expect(page.getByRole("heading", { name: /Сводка · R01/ })).toBeVisible();
  await expect(page.getByText("Главное за неделю")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Карта процессов" })).toBeVisible();
  await expectNoOverflow(page);

  await page.getByRole("button", { name: "Не согласен" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Не согласен" });
  await dialog.getByLabel("Другое").check();
  await expect(dialog.getByRole("button", { name: "Отправить" })).toBeDisabled(); // «Другое» needs a comment
  await dialog.getByLabel(/Комментарий/).fill("Был банкет на 80 гостей");
  await dialog.getByRole("button", { name: "Отправить" }).click();
  await expect(page.getByText("Отправлено в управляющую компанию")).toBeVisible();
  await expect(page.getByRole("button", { name: /Вы не согласны/ })).toBeVisible();

  // The same prototype session (no reload: the visitor's actions live in the page): the HQ signs in.
  await page.getByRole("button", { name: /Выйти/ }).first().click();
  await page.getByRole("button", { name: "Управляющая компания" }).click();
  await open(page, /Сводки/);
  await expect(page.getByRole("heading", { name: "Сводка сети" })).toBeVisible();
  await expect(page.getByText(/Был банкет на 80 гостей/)).toBeVisible();
});

test("TC-UI-19: the HQ opens a restaurant's digest and the archive", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Сводки/);
  await page.getByLabel("Чья сводка").selectOption({ index: 1 });
  await expect(page.getByRole("heading", { name: /Сводка · R01/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Не согласен" })).toHaveCount(0); // the HQ reviews, it does not disagree
  await page.getByLabel("Неделя").selectOption({ index: 2 });
  await expect(page.getByText(/Неделя 05\.10\.2026/)).toBeVisible();
});
