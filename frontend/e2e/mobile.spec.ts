// TC-UI-01, TC-UI-04 (docs/13-testing.md): every main screen fits a phone, for both roles, and the HQ
// reaches every section from a phone.
import { expect, test } from "@playwright/test";

import { expectNoOverflow, signIn } from "./helpers";

test.use({ viewport: { width: 390, height: 844 } });

for (const who of ["Управляющая компания", "Директор ресторана"] as const) {
  test(`TC-UI-01: no horizontal scroll at 390 px — ${who}`, async ({ page }) => {
    await signIn(page, who);
    await expectNoOverflow(page);
    const links = page.getByRole("navigation").getByRole("link");
    const count = await links.count();
    for (let i = 0; i < count; i++) {
      const link = links.nth(i);
      if (!(await link.isVisible())) continue;
      await link.click();
      await page.waitForTimeout(400);
      await expectNoOverflow(page);
    }
  });
}

test("TC-UI-04: from a phone the HQ opens every section through «Еще»", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  for (const section of ["Проверка находок", "Рестораны", "Отчет для руководителя", "Данные", "Нормы и настройки"]) {
    await page.getByRole("button", { name: /Еще/ }).click();
    await page.getByRole("dialog", { name: "Еще разделы" }).getByRole("link", { name: section }).click();
    await expect(page.getByRole("dialog", { name: "Еще разделы" })).toHaveCount(0);
    await expectNoOverflow(page);
  }
  await expect(page.getByRole("heading", { name: /Нормы|Настройки/ }).first()).toBeVisible();
});

test("TC-UI-13: «Еще» is a dialog for the keyboard: focus inside, Escape closes and returns focus", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  const button = page.getByRole("button", { name: /Еще разделы/ });
  await button.click();
  const menu = page.getByRole("dialog", { name: "Еще разделы" });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("link").first()).toBeFocused();
  for (let i = 0; i < 8; i++) await page.keyboard.press("Tab");
  expect(await menu.evaluate((m) => m.contains(document.activeElement))).toBe(true); // the focus stays inside
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(button).toBeFocused();
  // Any other tab closes it too.
  await button.click();
  await page.getByRole("navigation", { name: "Меню" }).getByRole("link", { name: /Находки/ }).click({ force: true });
  await expect(page.getByRole("dialog", { name: "Еще разделы" })).toHaveCount(0);
});
