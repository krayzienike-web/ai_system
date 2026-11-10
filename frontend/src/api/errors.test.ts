// Pre-pilot review 10.11.2026 (TC-UI-30…33): what a person reads when the server or the connection fails, where
// they return after the session ends, and what the upload refuses before sending.
import { afterEach, describe, expect, it, vi } from "vitest";

import { fileProblem } from "../app/DataPage";
import { safeNext } from "../lib/safeNext";
import { api, ApiError, errorDetail, OFFLINE, onSessionEnded, statusText, stream } from "./client";

function storage(entries: [string, string][] = []) {
  const store = new Map(entries);
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => store.set(k, v),
    removeItem: (k: string) => store.delete(k),
  });
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
  onSessionEnded(() => {});
});

describe("errors in Russian (TC-UI-30)", () => {
  it("keeps the server's words and says the status itself when there are none", () => {
    expect(errorDetail(422, { detail: "Строка 5: неизвестная единица" })).toBe("Строка 5: неизвестная единица");
    // Pydantic's list, an HTML page of a proxy, HTTP/2 without statusText: never an empty line
    expect(errorDetail(422, { detail: [{ loc: ["body"], msg: "field required" }] })).toBe(statusText(422));
    expect(errorDetail(413, {})).toMatch(/до 20 МБ/);
    expect(errorDetail(502, null)).toMatch(/Сервер не ответил/);
    expect(errorDetail(500, { detail: "  " })).toMatch(/Сервер не ответил/);
    for (const s of [401, 403, 404, 409, 429, 503]) expect(statusText(s)).toMatch(/[а-я]/);
  });

  it("answers a 413 and a 502 without a JSON body in Russian", async () => {
    storage();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Request Entity Too Large</html>", { status: 413 })));
    await expect(api("/imports", { method: "POST" })).rejects.toMatchObject({ status: 413, message: statusText(413) });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Bad Gateway", { status: 502, statusText: "" })));
    await expect(api("/overview/network")).rejects.toMatchObject({ status: 502, message: statusText(502) });
  });

  it("says «no connection» instead of «Failed to fetch», in requests and in the chat", async () => {
    storage();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(api("/tasks")).rejects.toEqual(new ApiError(0, OFFLINE));
    await expect(stream("/chat/stream", {}, () => {})).rejects.toMatchObject({ status: 0, message: OFFLINE });
  });
});

describe("the end of a session (TC-UI-31)", () => {
  it("any refused request ends the session once the refresh fails, not only «me»", async () => {
    const store = storage([
      ["fai.access", "a1"],
      ["fai.refresh", "r1"],
    ]);
    const ended = vi.fn();
    onSessionEnded(ended);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Invalid token" }), { status: 401 })),
    );
    await expect(api("/imports", { method: "POST" })).rejects.toMatchObject({ status: 401 });
    expect(ended).toHaveBeenCalledTimes(1);
    expect(store.size).toBe(0);
  });

  it("a wrong password on the login is not the end of a session", async () => {
    storage();
    const ended = vi.fn();
    onSessionEnded(ended);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Неверный email или пароль" }), { status: 401 })));
    await expect(api("/auth/login", { method: "POST" }, false)).rejects.toMatchObject({ status: 401 });
    expect(ended).not.toHaveBeenCalled();
  });

  it("returns only to a page of this app after signing in", () => {
    expect(safeNext("/checks/42?tab=result")).toBe("/checks/42?tab=result");
    for (const bad of ["//evil.com", "https://evil.com", "/\\evil.com", "evil.com", "/login?next=/", 42, undefined, "/\nx"])
      expect(safeNext(bad)).toBeUndefined();
  });
});

describe("the upload refuses before sending (TC-UI-32)", () => {
  it("a file that is not a table, too big or empty", () => {
    expect(fileProblem({ name: "Продажи.XLSX", size: 1000 })).toBeNull();
    expect(fileProblem({ name: "выгрузка.csv", size: 20 * 1024 * 1024 })).toBeNull();
    expect(fileProblem({ name: "акт.pdf", size: 1000 })).toMatch(/не таблица/);
    expect(fileProblem({ name: "Продажи.xlsx", size: 20 * 1024 * 1024 + 1 })).toMatch(/больше 20 МБ/);
    expect(fileProblem({ name: "Продажи.xlsx", size: 0 })).toBe("Файл пустой");
  });
});
