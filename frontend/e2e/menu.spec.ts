// TC-UI-46 (docs/13-testing.md): menu engineering — the HQ sees every category as four quadrants and a table;
// a restaurant's sales change the popularity; a director has no such screen.
import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

test("TC-UI-46: the HQ reads the menu matrix of the network and of one restaurant", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /^Меню/);
  await expect(page.getByRole("heading", { name: "Меню: популярность и маржа" })).toBeVisible();
  const pizza = page.getByRole("group", { name: "Матрица: Пицца" });
  await expect(pizza.getByText("Пицца Четыре сыра")).toBeVisible(); // a puzzle (net-four-cheese-puzzle)
  await expect(pizza.locator("div", { hasText: /^Загадки/ }).getByText("Пицца Четыре сыра")).toBeVisible();
  const hot = page.getByRole("group", { name: "Матрица: Горячее" });
  await expect(hot.locator("div", { hasText: /^Рабочие лошадки/ }).getByText("Куриные котлеты")).toBeVisible();
  await expect(page.getByText(/Не посчитаны.*Тыквенный суп/)).toBeVisible();
  await page.getByLabel("Чьи продажи").selectOption({ label: "Продажи: Ресторан на Тверской" });
  await expect(page.getByRole("group", { name: "Матрица: Пицца" })).toBeVisible();
});

test("TC-UI-46: a director has no menu screen", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  await expect(page.getByRole("link", { name: /^Меню/ })).toHaveCount(0);
});
