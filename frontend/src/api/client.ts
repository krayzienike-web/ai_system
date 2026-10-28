// Tokens live in localStorage for the MVP; moving the refresh token to an httpOnly cookie is planned.
const ACCESS = "fai.access";
const REFRESH = "fai.refresh";

/** Standalone demo build: no backend, auth and data are served in the browser (see demo.ts). */
export const DEMO = import.meta.env.VITE_DEMO === "1";

// Storage can be unavailable (private mode, sandboxed frames): fall back to memory.
const memory = new Map<string, string>();
const storage = {
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
  ) {
    super(message);
  }
}

export const tokens = {
  get access() {
    return storage.get(ACCESS);
  },
  get refresh() {
    return storage.get(REFRESH);
  },
  set(pair: { access_token: string; refresh_token: string }) {
    storage.set(ACCESS, pair.access_token);
    storage.set(REFRESH, pair.refresh_token);
  },
  clear() {
    storage.remove(ACCESS);
    storage.remove(REFRESH);
  },
};

async function tryRefresh(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  const response = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!response.ok) {
    tokens.clear();
    return false;
  }
  tokens.set(await response.json());
  return true;
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
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (response.status === 401 && retry && (await tryRefresh())) {
    return api<T>(path, init, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<void> {
  tokens.set(
    await api(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    ),
  );
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
  const response = await fetch(`/api${path}`, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (response.status === 401 && retry && (await tryRefresh())) return stream<T>(path, body, onStatus, signal, false);
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof detail.detail === "string" ? detail.detail : response.statusText);
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
