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
  if (init.method !== "PUT") return params;
  if (!isAdmin)
    throw new ApiError(
      403,
      "Параметры движка меняет администратор управляющей компании",
    );
  const { values } = JSON.parse(String(init.body)) as {
    values: Record<string, string | null>;
  };
  for (const [key, raw] of Object.entries(values)) {
    const p = params.find((x) => x.key === key);
    if (!p) throw new ApiError(422, `Неизвестный параметр «${key}»`);
    if (raw === null) {
      p.value = p.default;
      continue;
    }
    const n = Number(String(raw).replace(",", "."));
    if (!Number.isFinite(n) || n < Number(p.low) || n > Number(p.high))
      throw new ApiError(422, `«${p.title}»: от ${p.low} до ${p.high}`);
    p.value = String(n);
  }
  return params;
}
