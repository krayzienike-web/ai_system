// The standalone prototype replays the server's answers and must follow the server's access rules
// (ADR 0007; CLAUDE.md, principle 2).
import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { demoRequest } from "./demo";
import snapshot from "./demo/snapshot.json";
import type { ApiFinding, ApiTask, Check, EngineParam, ImportBatch, Restaurant } from "./types";

const ADMIN = "admin@demo.local";
const ANALYST = "analyst@demo.local";
const DIRECTOR = "director1@demo.local"; // R01
const users = snapshot.users as unknown as Record<string, { answers: Record<string, unknown> }>;

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
/** Decimal strings compared as numbers: "12.50" and "12.5" are the same money. */
const numbers = (value: unknown) =>
  JSON.parse(JSON.stringify(value), (_, v: unknown) => (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v)) as unknown;
const r01 = () => get<Restaurant[]>("/restaurants", DIRECTOR)[0]!;

describe("demo replays the server", () => {
  // Runs first: the actions below change the session's state.
  it("filters the findings list exactly as the server did", () => {
    for (const [email, { answers }] of Object.entries(users)) {
      const variants = Object.keys(answers).filter((p) => p.startsWith("/overview/findings"));
      expect(variants.length).toBeGreaterThan(1);
      for (const path of variants) expect(numbers(get(path, email)), `${email} ${path}`).toEqual(numbers(answers[path]));
    }
  });

  it("returns the recorded answers as copies", () => {
    const first = get<ApiFinding[]>("/findings", ADMIN);
    first[0]!.title = "changed";
    expect(get<ApiFinding[]>("/findings", ADMIN)[0]!.title).not.toBe("changed");
  });

  it("answers the chat from the recorded answers", () => {
    const [f] = get<ApiFinding[]>("/findings", DIRECTOR);
    const answer = send<{ text: string }>("/chat", DIRECTOR, "POST", { question: "Почему так получилось?", finding_id: f!.id });
    expect(answer.text).toBeTruthy();
    expect(send<{ text: string }>("/chat", DIRECTOR, "POST", { question: "что-то совсем другое" }).text).toBeTruthy();
  });
});

describe("demo isolation", () => {
  it("shows a director only their restaurant", () => {
    expect(get<Restaurant[]>("/restaurants", DIRECTOR).map((r) => r.code)).toEqual(["R01"]);
    expect(get<Restaurant[]>("/restaurants", ADMIN).length).toBeGreaterThan(1);
    expect(get<ApiFinding[]>("/findings", DIRECTOR).every((f) => f.restaurant_id === r01().id)).toBe(true);
    expect(status(() => get("/overview/restaurants/R02", DIRECTOR))).toBe(404);
    for (const path of ["/overview/restaurants", "/overview/network?preset=week", "/reports/head?preset=week", "/checks"])
      expect(status(() => get(path, DIRECTOR)), path).toBe(403);
  });

  it("keeps the review to HQ and hides unchecked findings from directors", () => {
    expect(status(() => get("/findings?review=pending", DIRECTOR))).toBe(403);
    const pending = get<ApiFinding[]>("/findings?review=pending", ANALYST);
    expect(pending.length).toBeGreaterThan(0);
    expect(status(() => get(`/findings/${pending[0]!.id}/verification`, DIRECTOR))).toBe(403);
    expect(status(() => send(`/findings/${pending[0]!.id}/review`, DIRECTOR, "POST", { verdict: "confirm" }))).toBe(403);
    expect(status(() => send("/tasks", ADMIN, "POST", { title: "x", due_on: "2026-10-27", finding_id: pending[0]!.id }))).toBe(422);

    // A finding of R01 sent back to review disappears for its director, and comes back once confirmed.
    const own = get<ApiFinding[]>("/findings", DIRECTOR).find((f) => f.review_status === "confirmed")!;
    send(`/findings/${own.id}/review`, ANALYST, "POST", { verdict: "reopen" });
    expect(get<ApiFinding[]>("/findings", DIRECTOR).map((f) => f.id)).not.toContain(own.id);
    expect(status(() => get(`/findings/${own.id}`, DIRECTOR))).toBe(404);
    expect(get<ApiFinding[]>("/findings?review=pending", ANALYST).map((f) => f.id)).toContain(own.id);

    const confirmed = send<ApiFinding>(`/findings/${own.id}/review`, ANALYST, "POST", { verdict: "confirm" });
    expect(confirmed.reviewed_by_name).toBe("Аналитик УК");
    const seen = get<ApiFinding[]>("/findings", DIRECTOR).find((f) => f.id === own.id)!;
    expect(seen.reviewed_by_name).toBeNull(); // the reviewer's name is HQ's
    expect(get<{ id: string }>(`/findings/${own.id}`, DIRECTOR).id).toBe(own.id);
  });

  it("opens «Документы» by the card's rules: own checked finding only (TC-ISO-17)", () => {
    const own = get<ApiFinding[]>("/findings", DIRECTOR).find((f) => `/findings/${f.id}/sources` in users[DIRECTOR]!.answers)!;
    expect(status(() => get(`/findings/${own.id}/sources`, DIRECTOR))).toBe(200);
    const other = get<ApiFinding[]>("/findings", ADMIN).find((f) => f.restaurant_id && f.restaurant_id !== r01().id)!;
    expect(status(() => get(`/findings/${other.id}/sources`, ADMIN))).toBe(200);
    expect(status(() => get(`/findings/${other.id}/sources`, DIRECTOR))).toBe(404);
    // Sent back to the check: the card is gone for the director, and so are its documents (as on the server).
    send(`/findings/${own.id}/review`, ANALYST, "POST", { verdict: "reopen" });
    expect(status(() => get(`/findings/${own.id}`, DIRECTOR))).toBe(404);
    expect(status(() => get(`/findings/${own.id}/sources`, DIRECTOR))).toBe(404);
    send(`/findings/${own.id}/review`, ANALYST, "POST", { verdict: "confirm" });
    expect(status(() => get(`/findings/${own.id}/sources`, DIRECTOR))).toBe(200);
  });

  it("lets only the HQ admin press «Пересчитать», as the server's `analytics.run` (TC-ENG-26)", () => {
    for (const who of [DIRECTOR, ANALYST]) expect(status(() => send("/analytics/run", who, "POST")), who).toBe(403);
    expect(send<{ trigger: string }>("/analytics/run", ADMIN, "POST").trigger).toBe("manual");
  });

  it("asks why a finding is rejected", () => {
    const [f] = get<ApiFinding[]>("/findings?review=pending", ADMIN);
    expect(status(() => send(`/findings/${f!.id}/review`, ADMIN, "POST", { verdict: "reject" }))).toBe(422);
    expect(status(() => send(`/findings/${f!.id}/review`, ADMIN, "POST", { verdict: "reject", reason: "logic" }))).toBe(422);
  });

  it("does not let a director touch another restaurant's files", async () => {
    const other = get<Restaurant[]>("/restaurants", ADMIN).find((r) => r.code === "R02")!.id;
    const upload = (restaurant: string | null, token: string) => {
      const form = new FormData();
      form.set("file", new File(["Дата;Блюдо;Кол-во;Сумма\n"], "sales.csv"));
      form.set("template", "sales");
      if (restaurant) form.set("restaurant_id", restaurant);
      return send<Promise<ImportBatch>>("/imports", token, "POST", form);
    };
    expect(status(() => upload(other, DIRECTOR))).toBe(403);
    expect(status(() => upload(null, DIRECTOR))).toBe(403);
    const batch = await upload(other, ADMIN);
    expect(status(() => send(`/imports/${batch.id}/publish`, DIRECTOR, "POST"))).toBe(404);
    expect(get<ImportBatch[]>("/imports", DIRECTOR).map((b) => b.id)).not.toContain(batch.id);
  });
});

describe("demo follows the server after the actions (code review 27.10.2026)", () => {
  const directors = Object.keys(users).filter((e) => e.startsWith("director"));
  const detail = (id: string, token: string) =>
    get<ApiFinding & { tasks: ApiTask[]; check: { status: string } | null }>(`/findings/${id}`, token);

  it("drops a «what to do» card once the director takes it into work", () => {
    const director = "director2@demo.local"; // R02: the demo's one untaken card
    const week = () => get<{ actions: ApiFinding[] }>("/overview/restaurants/R02", director).actions;
    const card = week()[0]!;
    send("/tasks", director, "POST", { title: card.title, due_on: "2026-11-10", finding_id: card.id });
    expect(week().map((f) => f.id)).not.toContain(card.id);
    expect(detail(card.id, director).work.stage).toBe("doing");
  });

  it("shows a check to HQ only, refuses a second one and keeps the director's own stage", () => {
    const draftKey = Object.keys(users[ANALYST]!.answers).find((k) => {
      const id = k.split("finding_id=")[1];
      return k.startsWith("/checks/draft") && directors.some((d) => get<ApiFinding[]>("/findings", d).some((f) => f.id === id && f.work.stage === "doing")) && // leaves the «new» ones to the tests below
        !["proposed", "running"].includes(detail(id!, ADMIN).check?.status ?? "");
    })!;
    const id = draftKey.split("finding_id=")[1]!;
    const director = directors.find((d) => get<ApiFinding[]>("/findings", d).some((f) => f.id === id))!;
    const draft = users[ANALYST]!.answers[draftKey] as { actions: string[] };
    const directorStage = detail(id, director).work.stage;
    const body = { finding_id: id, action: draft.actions[0], control_ids: [], weeks: 4 };
    const check = send<Check>("/checks", ANALYST, "POST", body);
    expect(status(() => send("/checks", ANALYST, "POST", body))).toBe(422);
    expect(detail(id, ADMIN).check?.status).toBe("proposed");
    expect(detail(id, ADMIN).work.check_waiting_launch).toBe(true);
    expect(detail(id, director).work.check_waiting_launch).toBe(false);

    send(`/checks/${check.id}/launch`, ADMIN, "POST");
    expect(detail(id, ADMIN).work.stage).toBe("checking");
    expect(detail(id, ADMIN).check?.status).toBe("running");
    expect(detail(id, director).work.stage).toBe(directorStage === "new" ? "doing" : directorStage);
    expect(detail(id, director).check).toBeNull();
  });

  it("never tells a director who reviewed a finding, in the list or in the detail", () => {
    const [f] = get<ApiFinding[]>("/findings", DIRECTOR);
    send(`/findings/${f!.id}/review`, ADMIN, "POST", { verdict: "reopen" });
    send(`/findings/${f!.id}/review`, ADMIN, "POST", { verdict: "confirm", note: "сверила с накладными" });
    expect(detail(f!.id, ADMIN).reviewed_by_name).toBeTruthy();
    const seen = detail(f!.id, DIRECTOR);
    expect([seen.reviewed_by_name, seen.review_note, seen.review_reason]).toEqual([null, null, null]);
  });

  it("answers what the server would instead of breaking", () => {
    expect(status(() => get("/overview/network?date_from=2026-09-01&date_to=2026-09-30", ADMIN))).toBe(422);
    expect(status(() => send("/tasks/no-such-task/start", DIRECTOR, "POST"))).toBe(404);
    expect(status(() => send("/checks/no-such-check/launch", ADMIN, "POST"))).toBe(404);
    const task = get<ApiTask[]>("/tasks", DIRECTOR).find((t) => t.status !== "done")!;
    expect(status(() => send(`/tasks/${task.id}/checklist`, DIRECTOR, "POST", { index: 999, done: true }))).toBe(422);
  });
});


describe("demo actions", () => {
  it("takes a finding into work and lets only the director do the task", () => {
    const f = get<ApiFinding[]>("/findings", DIRECTOR).find((x) => x.work.stage === "new")!;
    const [task] = send<ApiTask[]>("/tasks", DIRECTOR, "POST", { title: f.actions[0] ?? f.title, due_on: "2026-10-27", finding_id: f.id, checklist: ["a", "b"] });
    expect(get<ApiFinding[]>("/findings", DIRECTOR).find((x) => x.id === f.id)!.work.stage).toBe("doing");
    expect(get<ApiTask[]>("/tasks", DIRECTOR).map((t) => t.id)).toContain(task!.id);
    expect(get<ApiTask[]>("/tasks", "director2@demo.local").map((t) => t.id)).not.toContain(task!.id);
    expect(status(() => send(`/tasks/${task!.id}/start`, "director2@demo.local", "POST"))).toBe(404);
    expect(status(() => send(`/tasks/${task!.id}/start`, ADMIN, "POST"))).toBe(403);

    send(`/tasks/${task!.id}/checklist`, DIRECTOR, "POST", { index: 1, done: true });
    const done = send<ApiTask>(`/tasks/${task!.id}/complete`, DIRECTOR, "POST", { report: "сделано" });
    expect(done.checklist_done).toEqual([false, true]);
    expect(done.status).toBe("done");
    expect(status(() => send(`/tasks/${task!.id}/start`, DIRECTOR, "POST"))).toBe(422);
  });

  it("reminds about overdue tasks from HQ only", () => {
    const late = get<ApiTask[]>("/tasks?late=true", ADMIN);
    expect(late.length).toBeGreaterThan(0);
    expect(status(() => send(`/tasks/${late[0]!.id}/remind`, ANALYST, "POST"))).toBe(403);
    expect(send<ApiTask>(`/tasks/${late[0]!.id}/remind`, ADMIN, "POST").reminded_on).toBe(snapshot.recorded_for);
    expect(get<ApiTask[]>("/tasks?late=true", ADMIN)[0]!.reminded_on).toBe(snapshot.recorded_for);
  });

  it("launches a proposed check only by the HQ admin", () => {
    const [proposed] = get<Check[]>("/checks?status=proposed", ADMIN);
    expect(status(() => send(`/checks/${proposed!.id}/launch`, ANALYST, "POST"))).toBe(403);
    expect(status(() => send(`/checks/${proposed!.id}/launch`, DIRECTOR, "POST"))).toBe(403);
    const tasks = send<ApiTask[]>(`/checks/${proposed!.id}/launch`, ADMIN, "POST");
    expect(tasks.length).toBe((proposed!.test ?? []).length);
    expect(get<Check[]>("/checks?status=proposed", ADMIN).map((c) => c.id)).not.toContain(proposed!.id);
    expect(get<{ tasks: ApiTask[] }>(`/checks/${proposed!.id}`, ADMIN).tasks.length).toBeGreaterThanOrEqual(tasks.length);
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
});
