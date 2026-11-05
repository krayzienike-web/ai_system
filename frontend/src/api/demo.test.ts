// The standalone prototype replays the server's answers and must follow the server's access rules
// (ADR 0007; CLAUDE.md, principle 2).
import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { demoRequest } from "./demo";
import snapshot from "./demo/snapshot.json";
import type { ApiFinding, ApiTask, Check, Digest, Disagreement, EngineParam, ImportBatch, Restaurant } from "./types";

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

describe("the prototype has no assistant (ADR 0007; code review 02.11.2026, front p. 2)", () => {
  it("says so for every viewer, whatever a recording holds", () => {
    for (const email of Object.keys(users)) {
      expect(get<{ assistant?: boolean }>("/overview/context", email).assistant, email).toBe(false);
    }
  });

  it("answers an action it has not recorded in Russian", () => {
    try {
      send("/findings/x/hypotheses", ADMIN, "POST");
      throw new Error("no error");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).message).toBe("В прототипе это действие недоступно");
    }
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

  it("a finding the HQ assigns leaves «Решить по находке» and only then reaches the director (ADR 0009)", () => {
    const own = get<Restaurant[]>("/restaurants", DIRECTOR)[0]!;
    const waiting = get<ApiFinding[]>("/overview/awaiting", ADMIN).find((f) => f.restaurant_id === own.id)!;
    expect(waiting).toBeDefined();
    expect(get<ApiFinding[]>("/findings", DIRECTOR).map((f) => f.id)).not.toContain(waiting.id);
    // Unseen by the director: «not found», as on the server (row-level security before the role's rule).
    expect(status(() => send("/tasks", DIRECTOR, "POST", { title: "x", due_on: "2026-11-10", finding_id: waiting.id }))).toBe(404);
    expect(status(() => get("/overview/awaiting", DIRECTOR))).toBe(403);
    send("/tasks", ADMIN, "POST", { title: waiting.actions[0] ?? waiting.title, due_on: "2026-11-10", finding_id: waiting.id });
    expect(get<ApiFinding[]>("/overview/awaiting", ADMIN).map((f) => f.id)).not.toContain(waiting.id);
    expect(get<ApiFinding[]>("/findings", DIRECTOR).find((f) => f.id === waiting.id)?.work.stage).toBe("doing");
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
  it("lets only the director do the task the HQ set on a finding", () => {
    // A network-wide finding waiting for the HQ: its task goes to every restaurant, R01 among them.
    const f = get<ApiFinding[]>("/overview/awaiting", ADMIN).find((x) => x.restaurant_id === null && x.actions.length)!;
    const own = get<Restaurant[]>("/restaurants", DIRECTOR)[0]!;
    const tasks = send<ApiTask[]>("/tasks", ADMIN, "POST", { title: f.actions[0]!, due_on: "2026-10-27", finding_id: f.id, checklist: ["a", "b"] });
    const task = tasks.find((t) => t.restaurant_id === own.id);
    const who = DIRECTOR;
    const other = "director2@demo.local";
    expect(get<ApiFinding[]>("/overview/awaiting", ADMIN).map((x) => x.id)).not.toContain(f.id);
    expect(get<ApiTask[]>("/tasks", who).map((t) => t.id)).toContain(task!.id);
    expect(get<ApiTask[]>("/tasks", other).map((t) => t.id)).not.toContain(task!.id);
    expect(status(() => send(`/tasks/${task!.id}/start`, other, "POST"))).toBe(404);
    expect(status(() => send(`/tasks/${task!.id}/start`, ADMIN, "POST"))).toBe(403);

    send(`/tasks/${task!.id}/checklist`, who, "POST", { index: 1, done: true });
    const done = send<ApiTask>(`/tasks/${task!.id}/complete`, who, "POST", { report: "сделано" });
    expect(done.checklist_done).toEqual([false, true]);
    expect(done.status).toBe("done");
    expect(status(() => send(`/tasks/${task!.id}/start`, who, "POST"))).toBe(422);
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

describe("demo digests (stage 6)", () => {
  it("shows a director their restaurant's digest and nobody else's", () => {
    const own = get<Digest>("/digests/latest", DIRECTOR);
    expect(own.scope).toBe("restaurant");
    expect(own.restaurant_id).toBe(r01().id);
    expect(status(() => get("/digests/disagreements", DIRECTOR))).toBe(403);
    const net = get<Digest>("/digests/latest", ADMIN);
    expect(net.scope).toBe("network");
  });

  it("keeps a director's «Не согласен» and shows it to the HQ", () => {
    const item = get<Digest>("/digests/latest", DIRECTOR).problems[0]!;
    const url = `/findings/${item.finding_id}/disagree`;
    expect(status(() => send(url, DIRECTOR, "POST", { reason: "other" }))).toBe(422);
    expect(status(() => send(url, ADMIN, "POST", { reason: "wrong_data" }))).toBe(403);
    send(url, DIRECTOR, "POST", { reason: "explained", comment: "Был банкет" });
    const shown = get<Digest>("/digests/latest", DIRECTOR).problems.find((i) => i.finding_id === item.finding_id)!;
    expect(shown.disagreed).toBe("explained");
    const [row] = get<Disagreement[]>("/digests/disagreements", ADMIN);
    expect(row).toMatchObject({ finding_id: item.finding_id, comment: "Был банкет" });
    expect(row!.restaurant.startsWith("R01")).toBe(true);
    send(url, DIRECTOR, "DELETE");
    expect(status(() => send(url, DIRECTOR, "DELETE"))).toBe(404);
  });

  it("rebuilds to the recorded digest", () => {
    const again = send<Digest>("/digests/rebuild", ADMIN, "POST", { restaurant_id: null });
    expect(again.id).toBe(get<Digest>("/digests/latest", ADMIN).id);
  });
});

describe("demo digests keep to the director's restaurant (TC-UI-22)", () => {
  it("answers another restaurant's digest, archive and rebuild like a missing one", () => {
    const own = get<Digest>("/digests/latest", DIRECTOR);
    const other = get<Restaurant[]>("/restaurants", ADMIN).find((r) => r.id !== own.restaurant_id)!;
    expect(status(() => get(`/digests/latest?restaurant_id=${other.id}`, DIRECTOR))).toBe(404);
    // Another restaurant's archive is empty, as on the server (row-level security).
    expect(get(`/digests/weeks?restaurant_id=${other.id}`, DIRECTOR)).toEqual([]);
    expect(status(() => send("/digests/rebuild", DIRECTOR, "POST", { restaurant_id: other.id }))).toBe(404);
    // The network's digest is the HQ's: a director without a restaurant named gets their own.
    expect(send<Digest>("/digests/rebuild", DIRECTOR, "POST", {}).restaurant_id).toBe(own.restaurant_id);
    expect(get<{ week_start: string }[]>("/digests/weeks", DIRECTOR).length).toBeGreaterThan(1);
  });

  it("refuses «Не согласен» with an item of another restaurant's digest", () => {
    const own = get<Digest>("/digests/latest", DIRECTOR);
    const mine = new Set([...own.problems, ...own.opportunities, ...own.risks].map((i) => i.finding_id));
    // Any other restaurant's digest item (most demo restaurants have none until the HQ sets tasks).
    const item = get<Restaurant[]>("/restaurants", ADMIN)
      .filter((r) => r.id !== own.restaurant_id)
      .flatMap((r) => {
        const d = get<Digest>(`/digests/latest?restaurant_id=${r.id}`, ADMIN);
        return [...d.problems, ...d.opportunities, ...d.risks];
      })
      .find((i) => !mine.has(i.finding_id))!;
    expect(item).toBeDefined();
    expect(status(() => send(`/findings/${item.finding_id}/disagree`, DIRECTOR, "POST", { reason: "wrong_data" }))).toBe(404);
    expect(get<Disagreement[]>("/digests/disagreements", ADMIN).some((d) => d.finding_id === item.finding_id)).toBe(false);
  });
});

describe("demo digests after the review (03.11.2026)", () => {
  it("never shows a director the network's revenue and filters the HQ's list by restaurant", () => {
    const own = get<Digest>("/digests/latest", DIRECTOR);
    expect(own.network_average?.revenue ?? null).toBeNull();
    const item = own.problems[0]!;
    send(`/findings/${item.finding_id}/disagree`, DIRECTOR, "POST", { reason: "wrong_data", comment: "Накладные" });
    const shown = get<Digest>("/digests/latest", DIRECTOR).problems[0]!;
    expect(shown.disagreed_comment).toBe("Накладные");
    const others = get<Restaurant[]>("/restaurants", ADMIN).filter((r) => r.id !== own.restaurant_id);
    expect(get<Disagreement[]>(`/digests/disagreements?restaurant_id=${own.restaurant_id}`, ADMIN)).toHaveLength(1);
    expect(get<Disagreement[]>(`/digests/disagreements?restaurant_id=${others[0]!.id}`, ADMIN)).toHaveLength(0);
    send(`/findings/${item.finding_id}/disagree`, DIRECTOR, "DELETE");
  });
});

describe("demo «Решить по находке» follows the review (code review 05.11.2026, p. 4)", () => {
  it("a finding confirmed in the session enters it, one sent back leaves it; the counters follow", () => {
    const inbox = () => get<{ inbox: number }>("/overview/badges", ADMIN).inbox;
    const net = () => get<{ findings_awaiting: number }>("/overview/network?preset=week", ADMIN).findings_awaiting;
    const before = inbox();
    const pending = get<ApiFinding[]>("/findings?review=pending", ADMIN)[0]!;
    send(`/findings/${pending.id}/review`, ADMIN, "POST", { verdict: "confirm" });
    expect(get<ApiFinding[]>("/overview/awaiting", ADMIN).map((f) => f.id)).toContain(pending.id);
    expect(inbox()).toBe(before + 1);
    expect(net()).toBe(get<ApiFinding[]>("/overview/awaiting", ADMIN).length);
    send(`/findings/${pending.id}/review`, ADMIN, "POST", { verdict: "reopen" });
    expect(get<ApiFinding[]>("/overview/awaiting", ADMIN).map((f) => f.id)).not.toContain(pending.id);
    expect(inbox()).toBe(before);
  });
});

describe("demo «Поставить задачу» keeps the server's rules (test engineer, end of stage 6.1)", () => {
  const network = () => get<ApiFinding[]>("/overview/awaiting", ADMIN).find((f) => f.restaurant_id === null)!;
  const OTHER = "director2@demo.local"; // R02

  it("a network finding given to part of the network reaches only those directors", () => {
    const f = network();
    expect(f).toBeDefined();
    const tasks = send<ApiTask[]>("/tasks", ADMIN, "POST", { title: "Часть сети", due_on: "2026-11-10", finding_id: f.id, restaurant_ids: [r01().id] });
    expect(tasks.map((t) => t.restaurant_id)).toEqual([r01().id]);
    expect(get<ApiFinding[]>("/overview/awaiting", ADMIN).map((x) => x.id)).not.toContain(f.id);
    expect(get<ApiTask[]>("/tasks", DIRECTOR).map((t) => t.id)).toContain(tasks[0]!.id);
    expect(get<ApiTask[]>("/tasks", OTHER).some((t) => t.finding_id === f.id)).toBe(false);
    for (const who of [DIRECTOR, OTHER]) {
      expect(get<ApiFinding[]>("/findings", who).map((x) => x.id), who).not.toContain(f.id);
      expect(status(() => get(`/findings/${f.id}`, who)), who).toBe(404);
    }
  });

  it("the analyst sees «Решить по находке» but cannot put the task", () => {
    const f = get<ApiFinding[]>("/overview/awaiting", ANALYST)[0]!;
    expect(status(() => send("/tasks", ANALYST, "POST", { title: "x", due_on: "2026-11-10", finding_id: f.id }))).toBe(403);
    expect(get<ApiFinding[]>("/overview/awaiting", ADMIN).map((x) => x.id)).toContain(f.id);
  });

  // Server: tasks/service.py `_targets` — «A restaurant's finding can only be assigned to that restaurant» (422).
  it("refuses to give a restaurant's finding to another restaurant (found 05.11.2026, fixed)", () => {
    const f = get<ApiFinding[]>("/overview/awaiting", ADMIN).find((x) => x.restaurant_id !== null)!;
    const other = get<Restaurant[]>("/restaurants", ADMIN).find((r) => r.id !== f.restaurant_id)!;
    expect(status(() => send("/tasks", ADMIN, "POST", { title: "x", due_on: "2026-11-10", finding_id: f.id, restaurant_ids: [other.id] }))).toBe(422);
  });

  // Server: `tasks_out` reads findings under the director's row-level security — a network finding is not theirs,
  // so the director's task carries no finding title or network sum, and says «Поставлено управляющей компанией».
  it("does not name a network finding nor its network sum in the director's task (found 05.11.2026, fixed)", () => {
    const f = network();
    send("/tasks", ADMIN, "POST", { title: "Всем", due_on: "2026-11-10", finding_id: f.id });
    const mine = get<ApiTask[]>("/tasks", DIRECTOR).find((t) => t.finding_id === f.id)!;
    expect(mine.finding_title).toBeNull();
    expect(mine.finding_effect_rub_month).toBeNull();
    expect(mine.source).toBe("Поставлено управляющей компанией");
  });
});
