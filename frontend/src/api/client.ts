import { DemoAuthError, demoRequest } from "./demo";

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

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  if (DEMO) {
    try {
      return (await demoRequest(path, init, tokens.access)) as T;
    } catch (e) {
      throw e instanceof DemoAuthError ? new ApiError(401, e.message) : e;
    }
  }
  const headers = new Headers(init.headers);
  // A file upload (FormData) sets its own multipart content type.
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (response.status === 401 && retry && (await tryRefresh())) {
    return api<T>(path, init, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<void> {
  tokens.set(await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false));
}
