// TC-UI-47 (docs/13-testing.md): «Фудкост сети» on the HQ's overview (comment of 16.11.2026) — the actual
// share, the recipes' share and the network's target on one scale, the gap in points and rubles a month.
import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("TC-UI-47: the HQ reads the food cost against the recipes and the target", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  const block = page.getByRole("region", { name: "Показатели сети" });
  await expect(block.getByRole("img", { name: /^Фудкост 19,6%, по техкартам 19,1%, цель сети 30%$/ })).toBeVisible();
  await expect(block.getByText("выше техкарт, в пределах цели")).toBeVisible();
  await expect(block.getByText(/Кухни расходуют на 0,5 п\.п\. больше, чем по техкартам — ≈ 241,3 тыс ₽ в месяц/)).toBeVisible();
  await block.getByRole("link", { name: "Где именно →" }).click();
  await expect(page.getByRole("heading", { name: "Находки сети" })).toBeVisible();
});
