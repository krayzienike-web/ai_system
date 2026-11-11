// The session on the real API (TC-UI-31, TC-UI-34): a handed-out password is changed first, the session survives
// a reload by its cookie, the page keeps no token in its storage, signing out ends it, a page asked for before the
// login opens after it.
import { execFileSync } from "node:child_process";

import { expect, test } from "@playwright/test";

// A network of its own for every test: a retried or restarted worker does not meet the one before
const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;

function cli(...args: string[]): string {
  return execFileSync("uv", ["run", "python", "-m", "app.cli", ...args], {
    cwd: "../backend",
    env: { ...process.env, FAI_ENV: "dev" },
    encoding: "utf-8",
  });
}

function network(): { name: string; email: string; password: string } {
  const id = unique();
  const name = `Живая проверка ${id}`;
  const email = `hq.${id}@live.test`;
  const out = cli("create-tenant", "--name", name, "--admin-email", email, "--admin-name", "Петрова А.");
  return { name, email, password: /пароль: (\S+)/.exec(out)![1] };
}

test("TC-UI-34: a handed-out password, a reload, signing out — the session in a cookie", async ({ page, context }) => {
  const { email: EMAIL, password: issued } = network();

  await page.goto("/data");
  await expect(page).toHaveURL(/\/login\?next=%2Fdata/);
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Пароль").fill(issued);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Задайте свой пароль" })).toBeVisible();

  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  const cookie = (await context.cookies()).find((c) => c.name === "fai_refresh");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/api/auth" });

  await page.goto("/report");
  await expect(page.getByRole("heading", { name: "Задайте свой пароль" })).toBeVisible();
  await page.getByLabel("Выданный пароль").fill(issued);
  await page.getByLabel("Новый пароль", { exact: true }).fill("my-own-password-1");
  await page.getByLabel("Повторите новый пароль").fill("my-own-password-2");
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await expect(page.getByText("Пароли не совпадают")).toBeVisible();
  await page.getByLabel("Повторите новый пароль").fill("my-own-password-1");
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await expect(page).toHaveURL(/\/report$/); // back to where the person was going

  await page.reload();
  await expect(page).toHaveURL(/\/report$/);
  await expect(page.locator("aside").getByText("Петрова А.")).toBeVisible();

  await page.locator("aside").getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect((await context.cookies()).find((c) => c.name === "fai_refresh")).toBeUndefined();
  await page.goto("/report");
  await expect(page).toHaveURL(/\/login\?next=%2Freport/);

  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Пароль").fill("my-own-password-1");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/report$/); // the page asked for before the login
});

test("TC-UI-31: a session ended on the server leads to the login and back after it", async ({ page, context }) => {
  const { name } = network();
  const email = `an.${unique()}@live.test`;
  const issued = /пароль: (\S+)/.exec(cli("add-user", "--tenant", name, "--email", email, "--name", "Аналитик", "--role", "hq_analyst"))?.[1];
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(issued!);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.getByLabel("Выданный пароль").fill(issued!);
  await page.getByLabel("Новый пароль", { exact: true }).fill("analyst-pass-1");
  await page.getByLabel("Повторите новый пароль").fill("analyst-pass-1");
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/report");
  await expect(page).toHaveURL(/\/report$/);

  cli("disable-user", "--email", email); // the operator disables the login: every sign-in ends at once
  await page.reload();
  await expect(page).toHaveURL(/\/login\?next=%2Freport/);
  expect((await context.cookies()).find((c) => c.name === "fai_refresh")).toBeUndefined();
  cli("enable-user", "--email", email);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill("analyst-pass-1");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/report$/);
});
