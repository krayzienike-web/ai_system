// The chat drawer (docs/08, part 2; docs/10-ux.md) on the prototype build. The prototype answers at once from
// the recorded answers: the stream's statuses, the conversation id and the daily limit need the server and are
// checked in client.test.ts and backend/tests/test_ai_chat.py.
import { expect, test } from "@playwright/test";

import { open, signInAs } from "./helpers";

test("TC-UI-15: from a finding the su-chef talks about it, answers with its source and is closed", async ({ page }) => {
  await signInAs(page, "admin@demo.local");
  await open(page, /^Находки$/);
  await page.getByRole("link", { name: /Говядина вырезка/ }).first().click();
  const title = ((await page.getByRole("heading", { level: 1 }).textContent()) ?? "").trim();
  expect(title).toContain("Говядина вырезка");
  await page.getByRole("button", { name: "Спросить су-шефа" }).last().click();

  const drawer = page.getByRole("complementary", { name: "Су-шеф" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("Говорим о:")).toBeVisible();
  await expect(drawer.getByText(title, { exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "Почему так получилось?" }).click();

  // The question, then the answer — announced to a screen reader — with a link to the finding it came from.
  await expect(drawer.getByText("Почему так получилось?").first()).toBeVisible();
  await expect(drawer.getByRole("status")).toContainText("Ответ су-шефа:");
  await expect(drawer.getByRole("button", { name: /Открыть находку/ })).toBeVisible();

  await drawer.getByRole("button", { name: "Закрыть" }).click();
  await expect(drawer).toHaveCount(0);
});

test("TC-UI-16: the director's su-chef offers questions about their restaurant and answers one", async ({ page }) => {
  await signInAs(page, "director1@demo.local");
  await page.getByRole("button", { name: "Спросить су-шефа" }).first().click();
  const drawer = page.getByRole("complementary", { name: "Су-шеф" });
  await expect(drawer.getByText(/данных вашего ресторана/)).toBeVisible();
  const input = drawer.getByRole("textbox", { name: "Вопрос су-шефу" });
  await expect(input).toHaveAttribute("maxlength", "1000"); // a longer question would get 422 (review 28.10, p. 5)
  const starter = drawer.locator("form").locator("..").getByRole("button").first();
  const question = (await starter.textContent()) ?? "";
  expect(question.length).toBeGreaterThan(0);
  await starter.click();
  await expect(drawer.getByRole("status")).toContainText("Ответ су-шефа:");
  await expect(drawer.getByText(question).first()).toBeVisible();
});
