// Code review 27.10.2026 (docs/reviews/2026-10-27-code-review.md): what the prototype must not let happen.
import { expect, test } from "@playwright/test";

import { open, signInAs } from "./helpers";

test("TC-UI-07: a card taken into work leaves «Моя неделя» and cannot be taken twice", async ({ page }) => {
  await signInAs(page, "director2@demo.local");
  const take = page.getByRole("button", { name: "Взять в работу" });
  await expect(take).toHaveCount(1);
  await take.click();
  await page.getByRole("dialog").getByRole("button", { name: "Взять в работу" }).click();
  await expect(page.getByText("Задача в «Моих задачах»")).toBeVisible();
  await expect(take).toHaveCount(0);
});

test("TC-UI-08: the HQ analyst sees checks and overdue tasks but no buttons they may not press", async ({ page }) => {
  await signInAs(page, "analyst@demo.local");
  await open(page, /Ждут решения/);
  await expect(page.getByRole("heading", { name: /Проверки к запуску/ })).toBeVisible();
  await expect(page.getByText("Запускает администратор УК").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Запустить" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Напомнить/ })).toHaveCount(0);
});

test("TC-UI-09: the period picker is only where the period matters", async ({ page }) => {
  const picker = page.locator('header button[aria-haspopup="dialog"]');
  await signInAs(page, "analyst@demo.local");
  await expect(picker).toHaveCount(1); // «Сеть»
  await open(page, /Ждут решения/);
  await expect(picker).toHaveCount(0);
  await signInAs(page, "director2@demo.local");
  await expect(picker).toHaveCount(0);
});

test("TC-UI-10: a finding opens down to the invoices, each with its file", async ({ page }) => {
  await signInAs(page, "admin@demo.local");
  await open(page, /^Находки$/);
  await page.getByRole("link", { name: /Говядина вырезка/ }).first().click();
  await page.getByRole("button", { name: /Документы/ }).click();
  const table = page.getByRole("table").last();
  await expect(table).toContainText("Накладная");
  await expect(table).toContainText(".csv");
  await expect(page.getByText(/Говядина вырезка · .*Мясной экспресс/)).toBeVisible(); // said once above the table
});

test("TC-UI-11: «Сеть» shows restaurants × processes; a cell opens that restaurant's findings there", async ({ page }) => {
  await signInAs(page, "admin@demo.local");
  await expect(page.getByText("Где именно теряем?")).toBeVisible();
  await expect(page.getByText("Переплаты поставщикам")).toBeVisible();
  await page.getByRole("button", { name: /на Тверской, Производство/ }).click();
  await expect(page.getByRole("heading", { name: "Находки сети" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Перерасход по техкарте: Сыр Моцарелла/ })).toBeVisible();
  await expect(page.getByRole("combobox").first()).toHaveValue(/.+/);
});

// The prototype keeps its history in memory, so the address is checked through what the screen shows.
test("TC-UI-14: the findings filters live in the address: the menu link clears them", async ({ page }) => {
  await signInAs(page, "admin@demo.local");
  await page.getByRole("button", { name: /на Тверской, Производство/ }).click();
  const place = page.getByRole("combobox", { name: "Ресторан" });
  const process = page.getByRole("combobox", { name: "Процесс" });
  await expect(process).toHaveValue("production");
  await process.selectOption("all");
  await expect(process).toHaveValue("all");
  await expect(place).not.toHaveValue("all");
  await page.getByRole("link", { name: /^Находки$/ }).first().click(); // «/findings» without filters
  await expect(place).toHaveValue("all");
});
