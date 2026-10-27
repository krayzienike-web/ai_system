// TC-REV-01..03 (docs/13-testing.md): an engine finding goes found → checked → in the working list,
// and the path stays traceable on both ends.
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

const PENDING = "Закончится до поставки: Паста спагетти"; // found today in the demo network, waits for review

test("TC-REV-01: a confirmed finding appears in Находки with its path", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Проверка находок/);
  await page.getByRole("link", { name: new RegExp(PENDING) }).click();

  const trace = page.getByLabel("Путь находки");
  await expect(trace).toContainText("Найдено движком");
  await expect(trace).toContainText("На проверке");
  await expect(page.getByText("Расчет по шагам")).toBeVisible();

  await page.getByRole("button", { name: /Подтвердить/ }).click();
  await expect(trace).toContainText("Проверено");
  await expect(trace).toContainText("Администратор УК");

  await page.getByRole("link", { name: /Открыть в находках/ }).click();
  await page.getByRole("link", { name: new RegExp(PENDING) }).first().click();
  await expect(page.getByLabel("Путь находки").first()).toContainText("Проверено");
});

test("TC-REV-02: rejecting for a logic error needs a description", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /Проверка находок/);
  await page.getByRole("link", { name: new RegExp(PENDING) }).click();
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
  await expect(page.getByRole("link").filter({ hasText: /./ }).first()).toBeVisible();
  await expect(page.getByText(PENDING)).toHaveCount(0);
});
