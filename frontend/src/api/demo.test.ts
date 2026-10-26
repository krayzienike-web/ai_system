// The standalone prototype must follow the server's access rules (CLAUDE.md, principle 2).
import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { demoRequest } from "./demo";
import type { ApiFinding, EngineParam, ImportBatch, Restaurant } from "./types";

const ADMIN = "admin@demo.local";
const ANALYST = "analyst@demo.local";
const DIRECTOR = "director1@demo.local"; // R01

const get = <T>(path: string, token: string) => demoRequest(path, {}, token) as T;
const send = <T>(path: string, token: string, method: string, body?: unknown) =>
  demoRequest(path, { method, body: body instanceof FormData ? body : JSON.stringify(body) }, token) as T;
const status = (fn: () => unknown) => {
  try {
    fn();
  } catch (e) {
    return e instanceof ApiError ? e.status : "not an ApiError";
  }
  return 200;
};

describe("demo isolation", () => {
  it("shows a director only their restaurant", () => {
    expect(get<Restaurant[]>("/restaurants", DIRECTOR).map((r) => r.code)).toEqual(["R01"]);
    expect(get<Restaurant[]>("/restaurants", ADMIN).length).toBeGreaterThan(1);
  });

  it("keeps the review to HQ and hides unchecked findings from directors", () => {
    expect(status(() => get("/findings?review=pending", DIRECTOR))).toBe(403);
    const pending = get<ApiFinding[]>("/findings?review=pending", ANALYST);
    expect(pending.length).toBeGreaterThan(0);
    const own = pending.find((f) => f.restaurant_id === "R01")!;
    expect(status(() => get(`/findings/${own.id}/verification`, DIRECTOR))).toBe(403);
    expect(get<ApiFinding[]>("/findings", DIRECTOR).map((f) => f.id)).not.toContain(own.id);

    const confirmed = send<ApiFinding>(`/findings/${own.id}/review`, ANALYST, "POST", { verdict: "confirm" });
    expect(confirmed.reviewed_by_name).toBe("Аналитик УК");
    const seen = get<ApiFinding[]>("/findings", DIRECTOR).find((f) => f.id === own.id)!;
    expect(seen.review_status).toBe("confirmed");
    expect(seen.reviewed_by_name).toBeNull(); // the reviewer's name is HQ's
    expect(get<ApiFinding[]>("/findings", DIRECTOR).every((f) => f.restaurant_id === "R01")).toBe(true);

    send(`/findings/${own.id}/review`, ANALYST, "POST", { verdict: "reopen" });
    expect(get<ApiFinding[]>("/findings", DIRECTOR).map((f) => f.id)).not.toContain(own.id);
  });

  it("asks why a finding is rejected", () => {
    const [f] = get<ApiFinding[]>("/findings?review=pending", ADMIN);
    expect(status(() => send(`/findings/${f!.id}/review`, ADMIN, "POST", { verdict: "reject" }))).toBe(422);
    expect(
      status(() => send(`/findings/${f!.id}/review`, ADMIN, "POST", { verdict: "reject", reason: "logic" })),
    ).toBe(422);
  });

  it("does not let a director touch another restaurant's files or network data", async () => {
    const upload = (restaurant: string | null, token: string) => {
      const form = new FormData();
      form.set("file", new File(["Дата;Блюдо;Кол-во;Сумма\n"], "sales.csv"));
      form.set("template", "sales");
      if (restaurant) form.set("restaurant_id", restaurant);
      return send<Promise<ImportBatch>>("/imports", token, "POST", form);
    };
    expect(status(() => upload("R02", DIRECTOR))).toBe(403);
    expect(status(() => upload(null, DIRECTOR))).toBe(403);
    const other = await upload("R02", ADMIN);
    expect(status(() => send(`/imports/${other.id}/publish`, DIRECTOR, "POST"))).toBe(404);
    expect(status(() => send(`/imports/${other.id}/rollback`, DIRECTOR, "POST"))).toBe(404);
    expect(get<ImportBatch[]>("/imports", DIRECTOR).map((b) => b.id)).not.toContain(other.id);
  });
});

describe("demo engine parameters", () => {
  const params = (token: string) => get<EngineParam[]>("/settings/engine", token);
  const overpay = (token: string) => params(token).find((p) => p.key === "M3_OVERPAY")!;

  it("are changed by the HQ admin only, within the range, all or nothing", () => {
    expect(status(() => send("/settings/engine", ANALYST, "PUT", { values: { M3_OVERPAY: "7" } }))).toBe(403);
    const before = overpay(ADMIN).value;
    const bad = { values: { M3_OVERPAY: "7", M1_Z: "1000" } };
    expect(status(() => send("/settings/engine", ADMIN, "PUT", bad))).toBe(422);
    expect(overpay(ADMIN).value).toBe(before); // the valid half was not applied either
    expect(status(() => send("/settings/engine", ADMIN, "PUT", { values: { M3_OVERPAY: "" } }))).toBe(422);

    send("/settings/engine", ADMIN, "PUT", { values: { M3_OVERPAY: "7" } });
    expect(overpay(DIRECTOR).value).toBe("7");
    send("/settings/engine", ADMIN, "PUT", { values: { M3_OVERPAY: null } });
    expect(overpay(ADMIN).value).toBe(overpay(ADMIN).default);
  });

  it("are returned as copies, so a cached list is never changed behind React Query's back", () => {
    const first = params(ADMIN);
    send("/settings/engine", ADMIN, "PUT", { values: { M3_OVERPAY: "8" } });
    expect(first.find((p) => p.key === "M3_OVERPAY")!.value).not.toBe("8");
    send("/settings/engine", ADMIN, "PUT", { values: { M3_OVERPAY: null } });
  });
});
