// Code review 27.10.2026 (docs/reviews/2026-10-27-code-review.md): what the prototype must not let happen.
import { expect, test } from "@playwright/test";

import { open, signIn, signInAs } from "./helpers";

test("TC-UI-07: the HQ sets a finding's task from «Решить по находке»; only then the director has it (ADR 0009)", async ({ page }) => {
  // The director has no «Взять в работу»: a finding's task is the HQ's decision.
  await signInAs(page, "director1@demo.local");
  await expect(page.getByRole("button", { name: "Взять в работу" })).toHaveCount(0);
  await open(page, /Задачи/);
  await expect(page.getByText("Оформлять списания в день, когда продукт испорчен")).toHaveCount(0);

  // The same prototype session (no reload): the HQ decides.
  await page.getByRole("button", { name: /Выйти/ }).first().click();
  await page.getByRole("button", { name: "Управляющая компания" }).click();
  await open(page, /Ждут решения/);
  await expect(page.getByRole("heading", { name: /Решить по находке/ })).toBeVisible();
  const row = page.getByRole("listitem").filter({ hasText: "59% списаний оформлено за 2 дня до инвентаризации" });
  await row.getByRole("button", { name: "Поставить задачу" }).click();
  const dialog = page.getByRole("dialog", { name: "Поставить задачу" });
  await expect(dialog.getByRole("checkbox").first()).toBeChecked(); // the first step, one task with a checklist
  await dialog.getByRole("button", { name: "Поставить задачу" }).click();
  await expect(page.getByText(/Задача поставлена директору/)).toBeVisible();
  await expect(page.getByText("59% списаний оформлено за 2 дня до инвентаризации")).toHaveCount(0);

  await page.getByRole("button", { name: /Выйти/ }).first().click();
  await page.getByRole("button", { name: "Директор ресторана" }).click();
  await open(page, /Задачи/);
  await expect(page.getByText("Оформлять списания в день, когда продукт испорчен").first()).toBeVisible();
});

test("TC-UI-08: the HQ analyst sees checks and overdue tasks but no buttons they may not press", async ({ page }) => {
  await signInAs(page, "analyst@demo.local");
  await open(page, /Ждут решения/);
  await expect(page.getByRole("heading", { name: /Проверки к запуску/ })).toBeVisible();
  await expect(page.getByText("Запускает администратор УК").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Запустить" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Напомнить/ })).toHaveCount(0);
  // «Решить по находке»: the analyst reads, the admin sets the task (review 05.11.2026, p. 5).
  await expect(page.getByRole("heading", { name: /Решить по находке/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Поставить задачу" })).toHaveCount(0);
  await expect(page.getByText("Задачу ставит администратор УК").first()).toBeVisible();
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

test("TC-UI-07: a network finding's task goes to the restaurants chosen, with the due date chosen", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Ждут решения/);
  const row = page.getByRole("listitem").filter({ hasText: "Цена выросла по всей сети: Лосось охлажденный" });
  await row.getByRole("button", { name: "Поставить задачу" }).click();
  const dialog = page.getByRole("dialog", { name: "Поставить задачу" });
  const places = dialog.getByRole("group", { name: "Рестораны" }).getByRole("checkbox");
  const count = await places.count();
  expect(count).toBeGreaterThan(2);
  for (let i = 2; i < count; i++) await places.nth(i).uncheck(); // only the first two restaurants
  await dialog.getByRole("button", { name: /2 недели/ }).click();
  await expect(dialog.getByRole("button", { name: /2 недели/ })).toHaveAttribute("aria-pressed", "true");
  await dialog.getByRole("button", { name: "Поставить задачу" }).click();
  await expect(page.getByText("Задача поставлена директорам: 2")).toBeVisible();
  await expect(page.getByText("Цена выросла по всей сети: Лосось охлажденный")).toHaveCount(0);
});

test("TC-UI-24: linked findings show their story on the card and lead to each other (stage 6.5)", async ({ page }) => {
  await signInAs(page, "admin@demo.local");
  await open(page, /^Находки$/);
  await page.getByRole("link", { name: /Затоваривание: Сливки 33%/ }).first().click();
  await expect(page.getByText("Это одна история?")).toBeVisible();
  await expect(page.getByText("Закупают больше, чем успевают использовать: Сливки 33%")).toBeVisible();
  await expect(page.getByText(/в итогах — один раз/)).toBeVisible();
  await page.getByRole("link", { name: "Списания выше сети: Сливки 33%" }).click();
  await expect(page.getByRole("heading", { name: "Списания выше сети: Сливки 33%" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Затоваривание: Сливки 33%" })).toBeVisible();
});

test("TC-UI-25: the director's week says how far the numbers can be trusted (data quality score)", async ({ page }) => {
  await signInAs(page, "director1@demo.local");
  await expect(page.getByText("Можно ли верить цифрам?")).toBeVisible();
  await expect(page.getByText(/Качество данных — \d+ из 100/)).toBeVisible();
  await expect(page.getByText(/Продается блюдо без техкарты: −10/)).toBeVisible();
});
