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

/** Signs in with a demo login that has no quick button (other directors, the HQ analyst). */
export async function signInAs(page: Page, email: string) {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill("demo12345");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("link", { name: /находки$/i }).first()).toBeVisible();
}
