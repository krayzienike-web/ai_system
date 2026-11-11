// The access token lives in the page's memory only; the refresh token in an httpOnly cookie the page never
// sees (pre-pilot review 10.11.2026, p. 5). A reload restores the session from the cookie (`restoreSession`).
// The prototype has no server and no cookie: it keeps its demo token in the browser's storage.
const DEMO_ACCESS = "fai.access";

/** Standalone demo build: no backend, auth and data are served in the browser (see demo.ts). */
export const DEMO = import.meta.env.VITE_DEMO === "1";

// Storage can be unavailable (private mode, sandboxed frames): fall back to memory.
const memory = new Map<string, string>();
const demoStorage = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return memory.get(key) ?? null;
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      memory.set(key, value);
    }
  },
  remove(key: string) {
    try {
      localStorage.removeItem(key);
    } catch {
      memory.delete(key);
    }
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** What the screen may act on (the server's `code`, e.g. «no_header»), so it never reads the words. */
    public code?: string,
  ) {
    super(message);
  }
}

export const OFFLINE = "Нет связи с сервером — проверьте интернет и попробуйте еще раз";

/**
 * What the person reads when the server sent no words of its own: behind HTTP/2 `statusText` is empty, a
 * proxy answers 413/502 in HTML, and a validation error carries a list (pre-pilot review 10.11.2026, p. 1).
 */
export function statusText(status: number): string {
  if (status === 413) return "Файл слишком большой — до 20 МБ. Разбейте выгрузку на несколько периодов";
  if (status === 401) return "Сессия закончилась — войдите снова";
  if (status === 403) return "Нет доступа к этому действию";
  if (status === 404) return "Не нашли — возможно, это уже удалили";
  if (status === 409) return "Это уже сделано или изменилось — обновите страницу";
  if (status === 422) return "Сервер не принял данные — проверьте, что заполнено";
  if (status === 429) return "Слишком много попыток — подождите минуту";
  if (status >= 500) return "Сервер не ответил — попробуйте через минуту";
  return `Ошибка ${status}`;
}

/** The server's own Russian words when it gave them, otherwise the status said in Russian. */
export function errorDetail(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" && detail.trim() ? detail : statusText(status);
}

/** `fetch` that says «no connection» in Russian instead of «Failed to fetch» (aborts stay aborts). */
async function send(input: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, OFFLINE);
  }
}

let access: string | null = null;

export const tokens = {
  get access(): string | null {
    return DEMO ? demoStorage.get(DEMO_ACCESS) : access;
  },
  set(token: string) {
    if (DEMO) demoStorage.set(DEMO_ACCESS, token);
    else access = token;
  },
  clear() {
    if (DEMO) demoStorage.remove(DEMO_ACCESS);
    access = null;
  },
};

let sessionEnded: () => void = () => {};
let passwordRequired: () => void = () => {};

/** What the app does when the server says the session is over (the shell sends the person to the login). */
export function onSessionEnded(handler: () => void): void {
  sessionEnded = handler;
}

/** What the app does when the server asks for a new password first (a password handed out by the operator). */
export function onPasswordRequired(handler: () => void): void {
  passwordRequired = handler;
}

function onSessionEnd(): void {
  if (!tokens.access) return; // not signed in: a wrong password on the login is not «the end»
  tokens.clear();
  sessionEnded();
}

let refreshing: Promise<boolean> | null = null;

/** A new access token from the cookie's sign-in; requests that meet a 401 at once share one refresh. */
function tryRefresh(): Promise<boolean> {
  if (DEMO) return Promise.resolve(false);
  refreshing ??= (async () => {
    try {
      const response = await send("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
      if (!response.ok) return false; // the caller ends the session (onSessionEnd)
      tokens.set(((await response.json()) as { access_token: string }).access_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/** Signed in, or signed in again from the cookie after a reload: the router asks before any screen. */
export async function restoreSession(): Promise<boolean> {
  return tokens.access !== null || (await tryRefresh());
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  if (DEMO) {
    // Loaded only in the demo build: the recorded answers and demo logins never reach a production bundle.
    const demo = await import("./demo");
    try {
      return (await demo.demoRequest(path, init, tokens.access)) as T;
    } catch (e) {
      throw e instanceof demo.DemoAuthError ? new ApiError(401, e.message) : e;
    }
  }
  const headers = new Headers(init.headers);
  // A file upload (FormData) sets its own multipart content type.
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);
  const response = await send(`/api${path}`, { ...init, headers });
  if (response.status === 401 && retry && (await tryRefresh())) {
    return api<T>(path, init, false);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { code?: unknown };
    if (response.status === 401 && !path.startsWith("/auth/login")) onSessionEnd();
    if (response.status === 403 && response.headers.get("X-Password-Change") === "required") passwordRequired();
    throw new ApiError(
      response.status,
      errorDetail(response.status, body),
      typeof body.code === "string" ? body.code : undefined,
    );
  }
  if (response.status === 204) return undefined as T; // no content: «Не согласен», its withdrawal
  return response.json() as Promise<T>;
}

/** Signs in; true when the password was handed out by the operator and must be changed first. */
export async function login(email: string, password: string): Promise<boolean> {
  const answer = await api<{ access_token: string; must_change_password?: boolean }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
  tokens.set(answer.access_token);
  return answer.must_change_password === true;
}

/** Signs out on this device: the server ends the sign-in and removes the cookie; offline, the page forgets
 * its token anyway. */
export async function logout(): Promise<void> {
  tokens.clear();
  if (DEMO) return;
  await send("/api/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => undefined);
}

/** The person's own new password: the other sign-ins end, this one goes on with a new token. */
export async function changePassword(current: string, next: string): Promise<void> {
  const answer = await api<{ access_token: string }>("/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password: current, new_password: next }),
  });
  tokens.set(answer.access_token);
}

const BROKEN = "Ответ прервался";

/** Server-Sent Events of a complete text: `event:` and its JSON `data:`; comments and keep-alives are skipped. */
export function parseEvents(text: string): { event: string; data: unknown }[] {
  const out: { event: string; data: unknown }[] = [];
  for (const block of text.replace(/\r\n?/g, "\n").split("\n\n")) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      const m = /^(event|data):\s?(.*)$/.exec(line);
      if (!m) continue;
      const [, field, value = ""] = m;
      if (field === "event") event = value;
      else data.push(value);
    }
    if (!data.length) continue;
    try {
      out.push({ event, data: JSON.parse(data.join("\n")) as unknown });
    } catch {
      throw new ApiError(502, BROKEN);
    }
  }
  return out;
}

/**
 * POST that answers with Server-Sent Events: `status` events go to `onStatus`, the `answer` event resolves,
 * an `error` event rejects with its HTTP status. Aborting the signal (the chat was closed) stops reading, and
 * the server stops the assistant. The prototype has no stream: it answers at once.
 */
export async function stream<T>(
  path: string,
  body: unknown,
  onStatus: (text: string) => void,
  signal?: AbortSignal,
  retry = true,
): Promise<T> {
  if (DEMO) return api<T>(path.replace(/\/stream$/, ""), { method: "POST", body: JSON.stringify(body), signal });
  const headers = new Headers({ "Content-Type": "application/json" });
  if (tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);
  const response = await send(`/api${path}`, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (response.status === 401 && retry && (await tryRefresh())) return stream<T>(path, body, onStatus, signal, false);
  if (!response.ok || !response.body) {
    const detail: unknown = await response.json().catch(() => ({}));
    if (response.status === 401) onSessionEnd();
    throw new ApiError(response.status, errorDetail(response.status, detail));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // A CR at the very end may be the first half of CRLF: wait for the next chunk before reading it.
      const ready = !done && buffer.endsWith("\r") ? buffer.length - 1 : buffer.length;
      buffer = buffer.slice(0, ready).replace(/\r\n?/g, "\n") + buffer.slice(ready);
      const cut = done ? buffer.length : buffer.lastIndexOf("\n\n");
      if (cut >= 0) {
        for (const e of parseEvents(buffer.slice(0, cut))) {
          if (e.event === "status") onStatus((e.data as { text: string }).text);
          if (e.event === "answer") return e.data as T;
          if (e.event === "error") {
            const err = e.data as { detail: string; status: number };
            throw new ApiError(err.status, err.detail);
          }
        }
        buffer = buffer.slice(cut);
      }
      if (done) throw new ApiError(502, BROKEN);
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

/** The server said «there is no such thing» (or «not yours», which it answers the same way). */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 403);
}
