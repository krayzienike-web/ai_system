// TC-UI-18, -19, -21, -23 (docs/13-testing.md): the weekly digest (stage 6) — a director reads theirs and says
// «Не согласен» with a reason, which the HQ then sees; the HQ switches between the network and a restaurant.
import { expect, test } from "@playwright/test";

import { expectNoOverflow, open, signIn, signInAs } from "./helpers";

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

test("TC-UI-21: reactions only on the latest week; a changed reason keeps the comment", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  await open(page, /Сводка/);
  const disagree = page.getByRole("button", { name: "Не согласен" });
  await expect(disagree).toHaveCount(1);
  await page.getByLabel("Неделя").selectOption({ index: 1 }); // the latest week, chosen in the archive list
  await expect(disagree).toHaveCount(1);
  await page.getByLabel("Неделя").selectOption({ index: 2 }); // an archive week: read, not acted on
  await expect(page.getByText(/Неделя 05\.10\.2026/)).toBeVisible();
  await expect(disagree).toHaveCount(0);

  await page.getByLabel("Неделя").selectOption({ index: 0 });
  await disagree.click();
  let dialog = page.getByRole("dialog", { name: "Не согласен" });
  await dialog.getByLabel(/Есть объяснение/).check();
  await dialog.getByLabel(/Комментарий/).fill("Банкет 30.10");
  await dialog.getByRole("button", { name: "Отправить" }).click();
  await page.getByRole("button", { name: /Вы не согласны/ }).click();
  dialog = page.getByRole("dialog", { name: "Не согласен" });
  await expect(dialog.getByLabel(/Комментарий/)).toHaveValue("Банкет 30.10");
});

test("TC-UI-23: «Беру в работу» makes a task to oneself (the item is «В работе»); «Обсудить с ИИ» opens the chat on it", async ({ page }) => {
  await signInAs(page, "director2@demo.local"); // R02: its item is not taken yet in the recording
  await open(page, /Сводка/);
  await page.getByRole("button", { name: "Беру в работу" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Взять в работу" });
  await expect(dialog.getByRole("checkbox").first()).toBeChecked(); // the server's first step, not invented
  await dialog.getByRole("button", { name: "Взять в работу" }).click();
  await expect(page.getByText("Задача в «Моих задачах»")).toBeVisible();
  await expect(page.getByText("В работе").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Беру в работу" })).toHaveCount(0);

  // «Обсудить с ИИ» — the chat with the item's finding (docs/08: no new API).
  const title = ((await page.getByRole("heading", { level: 3 }).first().textContent()) ?? "").trim();
  await page.getByRole("button", { name: "Обсудить с ИИ" }).first().click();
  const drawer = page.getByRole("complementary", { name: "Су-шеф" });
  await expect(drawer.getByText("Говорим о:")).toBeVisible();
  await expect(drawer.getByText(title, { exact: true })).toBeVisible();
});
