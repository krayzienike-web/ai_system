// Pre-pilot review 10.11.2026 (TC-UI-30…33): what a person reads when the server or the connection fails, where
// they return after the session ends, and what the upload refuses before sending.
import { afterEach, describe, expect, it, vi } from "vitest";

import { fileProblem } from "../app/DataPage";
import { passwordProblem } from "../pages/Password";
import { safeNext } from "../lib/safeNext";
import {
  api,
  ApiError,
  changePassword,
  errorDetail,
  login,
  logout,
  OFFLINE,
  onPasswordRequired,
  onSessionEnded,
  restoreSession,
  statusText,
  stream,
  tokens,
} from "./client";

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
  onPasswordRequired(() => {});
  tokens.clear();
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
    tokens.set("a1");
    const ended = vi.fn();
    onSessionEnded(ended);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Invalid token" }), { status: 401 })),
    );
    await expect(api("/imports", { method: "POST" })).rejects.toMatchObject({ status: 401 });
    expect(ended).toHaveBeenCalledTimes(1);
    expect(tokens.access).toBeNull();
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

describe("the session in a cookie (TC-UI-34, pre-pilot review p. 5)", () => {
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

  it("keeps the access token in memory only and never sees a refresh token", async () => {
    const store = storage();
    vi.stubGlobal("fetch", vi.fn(async () => json({ access_token: "a1", token_type: "bearer", must_change_password: false })));
    expect(await login("admin@a.ru", "secret-pass-1")).toBe(false);
    expect(tokens.access).toBe("a1");
    expect(store.size).toBe(0);
  });

  it("after a reload restores the session from the cookie, or says it is over", async () => {
    const fetch = vi.fn(async () => json({ access_token: "a2" }));
    vi.stubGlobal("fetch", fetch);
    expect(await restoreSession()).toBe(true);
    expect(tokens.access).toBe("a2");
    expect(fetch).toHaveBeenCalledWith("/api/auth/refresh", expect.objectContaining({ method: "POST", credentials: "same-origin" }));
    tokens.clear();
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Сессия закончилась — войдите снова" }, 401)));
    expect(await restoreSession()).toBe(false);
  });

  it("requests refused at once share one refresh and go on with the new token", async () => {
    tokens.set("old");
    let refreshes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        if (url === "/api/auth/refresh") {
          refreshes += 1;
          return json({ access_token: "new" });
        }
        const auth = new Headers(init.headers).get("Authorization");
        return auth === "Bearer new" ? json({ ok: true }) : json({ detail: "Войдите в систему" }, 401);
      }),
    );
    expect(await Promise.all([api("/tasks"), api("/findings")])).toEqual([{ ok: true }, { ok: true }]);
    expect(refreshes).toBe(1);
  });

  it("signing out asks the server to end the sign-in and forgets the token, even offline", async () => {
    tokens.set("a1");
    const fetch = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await logout();
    expect(fetch).toHaveBeenCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST" }));
    expect(tokens.access).toBeNull();
    tokens.set("a1");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await logout();
    expect(tokens.access).toBeNull();
  });

  it("a handed-out password leads to its change first, and the change gives a new token", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ access_token: "a1", must_change_password: true })));
    expect(await login("new@a.ru", "abcd-efgh-jkmn-pqrs")).toBe(true);
    const required = vi.fn();
    onPasswordRequired(required);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Сначала смените пароль, выданный администратором" }, 403, { "X-Password-Change": "required" })),
    );
    await expect(api("/tasks")).rejects.toMatchObject({ status: 403 });
    expect(required).toHaveBeenCalledTimes(1);
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Нет доступа к этому действию" }, 403)));
    await expect(api("/settings/norms")).rejects.toMatchObject({ status: 403 });
    expect(required).toHaveBeenCalledTimes(1); // an ordinary «no access» is not about the password
    vi.stubGlobal("fetch", vi.fn(async () => json({ access_token: "a2", must_change_password: false })));
    await changePassword("abcd-efgh-jkmn-pqrs", "my-own-password");
    expect(tokens.access).toBe("a2");
  });
});

describe("the session in a cookie: edge cases (TC-UI-35…37)", () => {
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

  it("TC-UI-35: a reload without a connection says the server is unreachable, not «sign in»; the next try refreshes again", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(restoreSession()).rejects.toMatchObject({ status: 503 });
    expect(tokens.access).toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>502</html>", { status: 502 })));
    await expect(restoreSession()).rejects.toMatchObject({ status: 503 }); // a proxy's page instead of the API
    const fetch = vi.fn(async () => json({ access_token: "back" }));
    vi.stubGlobal("fetch", fetch);
    await expect(restoreSession()).resolves.toBe(true); // a failed refresh is not remembered
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(tokens.access).toBe("back");
    await expect(restoreSession()).resolves.toBe(true); // signed in: no second refresh
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("TC-UI-35: the server down while refreshing is not the end of the session: the token stays, no login", async () => {
    tokens.set("old");
    const ended = vi.fn();
    onSessionEnded(ended);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/auth/refresh" ? new Response("Bad Gateway", { status: 502 }) : json({ detail: "Войдите в систему" }, 401),
      ),
    );
    await expect(api("/tasks")).rejects.toMatchObject({ status: 503 });
    await expect(stream("/chat/stream", {}, () => {})).rejects.toMatchObject({ status: 503 });
    expect(ended).not.toHaveBeenCalled();
    expect(tokens.access).toBe("old");
  });

  it("TC-UI-36: the chat's stream with a handed-out password leads to its change, as any request does", async () => {
    tokens.set("a1");
    const required = vi.fn();
    onPasswordRequired(required);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Сначала смените пароль, выданный администратором" }, 403, { "X-Password-Change": "required" })),
    );
    await expect(stream("/chat/stream", { question: "Почему?" }, () => {})).rejects.toMatchObject({
      status: 403,
      message: "Сначала смените пароль, выданный администратором",
    });
    expect(required).toHaveBeenCalledTimes(1);
    expect(tokens.access).toBe("a1"); // not the end of the session
  });

  it("TC-UI-37: the password page refuses before sending: too short, not repeated, the same as the current one", () => {
    const issued = "abcd-efgh-jkmn-pqrs";
    expect(passwordProblem(issued, "short", "short")).toBe("Новый пароль — не короче 10 символов");
    expect(passwordProblem(issued, "123456789", "123456789")).toMatch(/не короче 10/); // 9 characters
    expect(passwordProblem(issued, "😀😀😀😀😀", "😀😀😀😀😀")).toMatch(/не короче 10/); // 5 characters, 10 UTF-16 units
    expect(passwordProblem(issued, "my-own-password", "my-own-passwort")).toBe("Пароли не совпадают");
    expect(passwordProblem(issued, issued, issued)).toBe("Новый пароль должен отличаться от текущего");
    expect(passwordProblem(issued, "1234567890", "1234567890")).toBeNull(); // exactly 10: as the server allows
    expect(passwordProblem(issued, "my-own-password", "my-own-password")).toBeNull();
  });
});
