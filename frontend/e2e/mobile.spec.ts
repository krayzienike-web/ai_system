// TC-UI-01 (docs/13-testing.md): every main screen fits a phone, for both roles.
import { test } from "@playwright/test";

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
