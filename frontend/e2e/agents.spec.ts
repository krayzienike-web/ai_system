// TC-UI-38 (docs/13-testing.md): «Помощник» on the home screen (stage 9, ADR 0010). The director takes the list
// «что пересчитать внимательно» into work — it becomes a task with the list; the HQ admin moves a stuck task's
// deadline. What the notes say is the server's (the prototype replays it).
import { expect, test } from "@playwright/test";

import { open, signIn, signInAs } from "./helpers";

test("TC-UI-38: the director takes the inventory list into work", async ({ page }) => {
  await signIn(page, "Директор ресторана");
  const assistant = page.getByRole("region", { name: "Помощник" });
  const note = assistant.getByRole("listitem").filter({ hasText: "что пересчитать внимательно" });
  await expect(note).toBeVisible();
  await expect(note.getByText(/по нему открыта находка/).first()).toBeVisible();
  await note.getByRole("button", { name: "Создать задачу" }).click();
  await expect(page.getByText("Задача создана — она в «Задачах»")).toBeVisible();
  await expect(note).toHaveCount(0);
  await open(page, /Задачи/);
  await expect(page.getByText(/Подготовка к инвентаризации/).first()).toBeVisible();
});

test("TC-UI-38: the HQ admin moves a stuck task's deadline", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  const assistant = page.getByRole("region", { name: "Помощник" });
  const stuck = assistant.getByRole("listitem").filter({ hasText: "просрочена и не начата" });
  await expect(stuck).toBeVisible();
  await stuck.getByRole("button", { name: /Перенести на/ }).click();
  await expect(page.getByText(/Срок перенесен на/)).toBeVisible();
  await expect(stuck).toHaveCount(0);
});

test("TC-UI-38: the HQ analyst reads the notes but has no buttons to answer them", async ({ page }) => {
  await signInAs(page, "analyst@demo.local");
  const assistant = page.getByRole("region", { name: "Помощник" });
  await expect(assistant.getByRole("listitem").filter({ hasText: "просрочена и не начата" })).toBeVisible();
  for (const name of [/Перенести на/, "Создать задачу", "Не нужно", "Скрыть"])
    await expect(assistant.getByRole("button", { name })).toHaveCount(0);
});
