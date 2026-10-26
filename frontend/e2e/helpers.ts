import { expect, type Page } from "@playwright/test";

export async function signIn(page: Page, who: "Управляющая компания" | "Директор ресторана") {
  await page.goto("/");
  await page.getByRole("button", { name: who }).click();
  await expect(page.getByRole("link", { name: /находки$/i }).first()).toBeVisible();
}

export async function open(page: Page, section: RegExp) {
  await page.getByRole("link", { name: section }).first().click();
}

/** No horizontal scroll: everything fits the screen width. */
export async function expectNoOverflow(page: Page) {
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll, "page is wider than the screen").toBeLessThanOrEqual(width);
}
