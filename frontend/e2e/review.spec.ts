// TC-REV-01..04 (docs/13-testing.md): an engine finding goes found → checked → in the working list,
// and the path stays traceable on both ends.
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

test("TC-REV-01: a confirmed finding appears in Находки with its path, for HQ and the director", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Проверка находок/);
  await page.getByRole("link", { name: /Сыр Моцарелла/ }).click();

  const trace = page.getByLabel("Путь находки");
  await expect(trace).toContainText("Найдено движком");
  await expect(trace).toContainText("На проверке");
  await expect(page.getByText("Сверка с загруженными данными")).toBeVisible();

  await page.getByRole("button", { name: /Подтвердить/ }).click();
  await expect(trace).toContainText("Проверено");
  await expect(trace).toContainText("Администратор УК");

  await page.getByRole("link", { name: /Открыть в находках/ }).click();
  const checked = page.getByRole("region", { name: "Найдено движком и проверено" });
  await expect(checked).toContainText("Сыр Моцарелла");
  await expect(checked.getByLabel("Путь находки").first()).toContainText("В находках");
  await expect(checked.getByRole("link", { name: /Расчет и проверка/ }).first()).toBeVisible();
});

test("TC-REV-02: rejecting for a logic error needs a description", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Проверка находок/);
  await page.getByRole("link", { name: /Сыр Моцарелла/ }).click();
  await page.getByRole("button", { name: "Отклонить" }).click();
  await page.getByText("Ошибка в логике расчета").click();
  await page.getByRole("button", { name: "Отклонить" }).first().click();
  await expect(page.getByText(/Опишите, что не так/)).toBeVisible();
  await expect(page.getByLabel("Путь находки")).toContainText("На проверке"); // nothing was saved
});

test("TC-REV-03: the director sees neither the review nor unchecked findings", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  await expect(page.getByRole("link", { name: /Проверка находок/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Нормы и настройки/ })).toHaveCount(0);
  await open(page, /находки$/i);
  // Nothing is confirmed in a fresh prototype session: the engine block is not shown at all.
  await expect(page.getByRole("region", { name: "Найдено движком и проверено" })).toHaveCount(0);
});
