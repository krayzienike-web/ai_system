import { expect, test } from "@playwright/test";

import { open, signIn } from "./helpers";

// Pre-pilot review 10.11.2026 (TC-UI-33): a checked file that was left is finished from the history; a file
// that is not a table is refused before it is sent.
test("TC-UI-33: a checked file left unloaded is loaded from «Что загружали?»; a PDF is refused at once", async ({ page }) => {
  await signIn(page, "Управляющая компания");
  await open(page, /^Данные$/);
  const input = page.getByLabel("Файл выгрузки");

  await input.setInputFiles({ name: "акт.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
  await expect(page.getByRole("alert").filter({ hasText: "не таблица" })).toBeVisible();

  await input.setInputFiles({ name: "Продажи R01.xlsx", mimeType: "application/vnd.ms-excel", buffer: Buffer.from("PK") });
  await expect(page.getByRole("button", { name: /Загрузить в систему/ })).toBeVisible();
  await page.getByRole("button", { name: "Загрузить другой файл" }).click(); // left without loading

  const row = page.getByRole("listitem").filter({ hasText: "Продажи R01.xlsx" });
  await row.getByRole("button", { name: "Открыть и загрузить" }).click();
  await page.getByRole("button", { name: /Загрузить в систему/ }).click();
  await expect(page.getByText(/Загружено строк: 2\s050/)).toBeVisible();
});
