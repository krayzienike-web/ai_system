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
    await page.getByRole("navigation", { name: "Еще разделы" }).getByRole("link", { name: section }).click();
    await expect(page.getByRole("navigation", { name: "Еще разделы" })).toHaveCount(0);
    await expectNoOverflow(page);
  }
  await expect(page.getByRole("heading", { name: /Нормы|Настройки/ }).first()).toBeVisible();
});
