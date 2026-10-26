// Demo mode: the network's engine parameters kept in the browser, with the API's defaults and ranges.
import { ApiError } from "./client";
import defaults from "./demoEngine.json";
import type { EngineParam } from "./types";

const params: EngineParam[] = (defaults as EngineParam[]).map((p) => ({
  ...p,
}));

export function demoEngineParams(
  init: RequestInit,
  isAdmin: boolean,
): EngineParam[] {
  if (init.method !== "PUT") return params.map((p) => ({ ...p }));
  if (!isAdmin)
    throw new ApiError(
      403,
      "Параметры движка меняет администратор управляющей компании",
    );
  const { values } = JSON.parse(String(init.body)) as {
    values: Record<string, string | null>;
  };
  // Check everything first, then apply: a bad value leaves the settings as they were, like the server's transaction.
  const next = new Map<string, string>();
  for (const [key, raw] of Object.entries(values)) {
    const p = params.find((x) => x.key === key);
    if (!p) throw new ApiError(422, `Неизвестный параметр «${key}»`);
    if (raw === null) {
      next.set(key, p.default);
      continue;
    }
    const n = Number(String(raw).replace(",", "."));
    if (String(raw).trim() === "" || !Number.isFinite(n) || n < Number(p.low) || n > Number(p.high))
      throw new ApiError(422, `«${p.title}»: от ${p.low} до ${p.high}`);
    next.set(key, String(n));
  }
  for (const p of params) p.value = next.get(p.key) ?? p.value;
  return params.map((p) => ({ ...p }));
}
