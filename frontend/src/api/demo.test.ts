// The standalone prototype replays the server's answers and must follow the server's access rules
// (ADR 0007; CLAUDE.md, principle 2).
import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { board, demoRequest } from "./demo";
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
    const draft = users[ANALYST]!.answers[draftKey] as { actions: string[]; candidates: { restaurant_id: string; suggested: boolean }[] };
    const directorStage = detail(id, director).work.stage;
    // as the screen sends it: the suggested restaurants to compare with (a measured check needs them, stage 7)
    const controls = draft.candidates.filter((c) => c.suggested).map((c) => c.restaurant_id);
    const body = { finding_id: id, action: draft.actions[0], control_ids: controls, weeks: 4 };
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

  it("builds a finding's story for whoever looks, like the server (stage 6.5 review, frontend p. 2)", () => {
    const all = get<ApiFinding[]>("/findings", ADMIN);
    const over = all.find((f) => f.title === "Затоваривание: Руккола")!;
    expect(over.story?.findings.map((m) => m.title)).toEqual(["Списания выше сети: Руккола"]);
    // The HQ sends both rucola findings to R01: the director sees the story on both cards, naming only these.
    for (const f of all.filter((x) => x.restaurant_code === "R01" && x.story?.key === over.story?.key)) {
      if (!get<ApiFinding[]>("/findings", DIRECTOR).some((m) => m.id === f.id))
        send("/tasks", ADMIN, "POST", { title: f.actions[0] ?? f.title, due_on: "2026-11-10", finding_id: f.id });
    }
    const mine = get<ApiFinding[]>("/findings", DIRECTOR);
    const ids = new Set(mine.map((f) => f.id));
    const rucola = mine.filter((f) => f.story?.key === over.story?.key);
    expect(rucola.map((f) => f.title).sort()).toEqual(["Затоваривание: Руккола", "Списания выше сети: Руккола"]);
    for (const f of mine) for (const m of f.story?.findings ?? []) expect(ids.has(m.id) && m.restaurant_code === "R01").toBe(true);
    const card = get<ApiFinding>(`/findings/${over.id}`, DIRECTOR);
    expect(card.story?.findings.map((m) => m.title)).toEqual(["Списания выше сети: Руккола"]);
  });

  it("counts a story's money once across kinds, and a supplier story's findings add up (frontend p. 1)", () => {
    const base = get<ApiFinding[]>("/findings", ADMIN)[0]!;
    const make = (id: string, kind: "problem" | "opportunity", effect: number, key: string | null): ApiFinding => ({
      ...base,
      id,
      kind,
      process: "purchasing",
      restaurant_id: null,
      effect_rub_month: effect.toFixed(2),
      story: key ? { key, title: key, adds: key.startsWith("supplier:"), effect_rub_month: null, findings: [] } : null,
    });
    const scope = [
      make("a", "problem", 500, "price:net:P09"),
      make("b", "opportunity", 40, "price:net:P09"), // the same money as «a»: counted 0
      make("c", "problem", 30, "supplier:R02:P08"),
      make("d", "problem", 20, "supplier:R02:P08"), // different money: adds up
      make("e", "opportunity", 7, null),
    ];
    const totals = Object.fromEntries(board(scope, new URLSearchParams()).kinds.map((k) => [k.kind, Number(k.total)]));
    expect(totals).toEqual({ problem: 550, opportunity: 7 });
  });
});

describe("the prototype's data quality score follows the server's rules (stage 6.5, TC-UI-25, TC-UI-26)", () => {
  type Quality = { data_quality: number | null; data_quality_parts: { label: string; points: number }[] };
  type Week = { kpi: Quality; network_kpi: Quality; data_quality_low: number; data_quality_answer: string };
  type Kpis = { kpis: { data_quality: string | null }; network_average: { data_quality: string | null } };
  const week = (token: string) => get<Week>("/overview/restaurants/R01", token);

  it("gives a director the score without the network finding they are not shown, HQ the whole one", () => {
    const mine = week(DIRECTOR);
    const whole = week(ADMIN);
    // HQ: 100 − 10 for the soup sold without a recipe (a network finding); the director: without it
    expect(whole.kpi.data_quality).toBe(90);
    expect(whole.kpi.data_quality_parts).toEqual([{ label: "Продается блюдо без техкарты", points: 10 }]);
    expect(mine.kpi.data_quality).toBe(100);
    expect(mine.kpi.data_quality_parts).toEqual([]);
    for (const w of [mine, whole])
      expect(w.kpi.data_quality).toBe(100 - w.kpi.data_quality_parts.reduce((s, p) => s + p.points, 0));
    expect(mine.network_kpi.data_quality).toBe(whole.network_kpi.data_quality); // the network's average is one
  });

  it("says the same on the week and in the digest, with the limit from the server", () => {
    const mine = week(DIRECTOR);
    const digest = get<Kpis>("/digests/latest", DIRECTOR);
    expect(digest.kpis.data_quality).toBe(`${mine.kpi.data_quality} из 100`);
    expect(digest.network_average.data_quality).toBe(`${mine.network_kpi.data_quality} из 100`);
    expect(mine.data_quality_answer).toContain(`${mine.kpi.data_quality} из 100`);
    const low = get<EngineParam[]>("/settings/engine", ADMIN).find((p) => p.key === "M7_DQ_LOW")!;
    expect(mine.data_quality_low).toBe(Number(low.value));
  });
});

describe("demo checks keep the server's rules for reject and roll-out (test engineer, start of stage 7)", () => {
  it("rolls out only a confirmed check, by the HQ admin, once, to every restaurant that has not done it", () => {
    const checks = get<Check[]>("/checks", ADMIN);
    const worked = checks.find((c) => c.verdict === "confirmed" && !c.rollout_on)!;
    expect(worked).toBeDefined();
    expect(status(() => send(`/checks/${worked.id}/rollout`, ANALYST, "POST"))).toBe(403);
    expect(status(() => send(`/checks/${worked.id}/rollout`, DIRECTOR, "POST"))).toBe(403);
    for (const other of checks.filter((c) => c.verdict !== "confirmed"))
      expect(status(() => send(`/checks/${other.id}/rollout`, ADMIN, "POST")), other.title).toBe(422);
    const tested = new Set((worked.test ?? []).map((p) => p.id));
    const everyone = get<Restaurant[]>("/restaurants", ADMIN);
    const tasks = send<ApiTask[]>(`/checks/${worked.id}/rollout`, ADMIN, "POST");
    expect(new Set(tasks.map((t) => t.restaurant_id))).toEqual(new Set(everyone.filter((r) => !tested.has(r.id)).map((r) => r.id)));
    expect(new Set(tasks.map((t) => t.title))).toEqual(new Set([worked.title]));
    expect(get<Check>(`/checks/${worked.id}`, ADMIN).rollout_on).toBe(snapshot.recorded_for);
    expect(status(() => send(`/checks/${worked.id}/rollout`, ADMIN, "POST"))).toBe(422);
  });

  it("decides only a proposed check: a running or completed one is neither launched nor rejected again", () => {
    for (const c of get<Check[]>("/checks", ADMIN).filter((c) => c.status !== "proposed")) {
      expect(status(() => send(`/checks/${c.id}/reject`, ADMIN, "POST")), c.title).toBe(422);
      expect(status(() => send(`/checks/${c.id}/launch`, ADMIN, "POST")), c.title).toBe(422);
    }
    expect(status(() => send("/checks/no-such-check/reject", ADMIN, "POST"))).toBe(404);
    const [any] = get<Check[]>("/checks", ADMIN);
    expect(status(() => send(`/checks/${any!.id}/reject`, ANALYST, "POST"))).toBe(403);
    expect(status(() => send(`/checks/${any!.id}/reject`, DIRECTOR, "POST"))).toBe(403);
  });

  it("repeats a check without an effect longer, like the server (stage 7, TC-EXP-36)", () => {
    const checks = get<Check[]>("/checks", ADMIN);
    const bread = checks.find((c) => c.title === "Заказ хлеба по дням недели")!;
    const tomato = checks.find((c) => c.title === "Малые партии томатов")!;
    expect(bread.status).toBe("completed");
    expect(status(() => send(`/checks/${bread.id}/repeat`, DIRECTOR, "POST", { weeks: 6 }))).toBe(403);
    expect(status(() => send(`/checks/${bread.id}/repeat`, ADMIN, "POST", { weeks: bread.weeks }))).toBe(422);
    expect(status(() => send(`/checks/${tomato.id}/repeat`, ADMIN, "POST", { weeks: 6 }))).toBe(422);
    const again = send<Check>(`/checks/${bread.id}/repeat`, ANALYST, "POST", { weeks: bread.weeks + 2 });
    expect([again.status, again.weeks, again.design]).toEqual(["proposed", bread.weeks + 2, bread.design]);
    expect(get<Check[]>("/checks", ADMIN).find((c) => c.id === bread.id)?.status).toBe("completed");
  });

  it("proposes a check by the server's rules and fields (stage 7 review, frontend p. 3–4, 6)", () => {
    type Draft = {
      finding_id: string;
      actions: string[];
      measured: boolean;
      metric: string;
      candidates: { restaurant_id: string; suggested: boolean }[];
      designs: { design: string; available: boolean }[];
    };
    const drafts = Object.entries(users[ADMIN]!.answers)
      .filter(([k]) => k.startsWith("/checks/draft"))
      .map(([, d]) => d as Draft);
    const open = new Set(
      get<Check[]>("/checks", ADMIN)
        .filter((c) => c.status === "proposed" || c.status === "running")
        .map((c) => c.finding_id),
    );
    const d = drafts.find((x) => x.measured && x.designs.some((o) => o.design === "items" && o.available) && !open.has(x.finding_id))!;
    const controls = d.candidates.filter((c) => c.suggested).map((c) => c.restaurant_id);
    const body = { finding_id: d.finding_id, action: d.actions[0], control_ids: controls, weeks: 4 };
    expect(status(() => send("/checks", ADMIN, "POST", { ...body, design: "magic" }))).toBe(422);
    expect(status(() => send("/checks", ADMIN, "POST", { ...body, control_ids: ["not-a-restaurant"] }))).toBe(422);
    expect(status(() => send("/checks", ADMIN, "POST", { ...body, weeks: 5 }))).toBe(422);
    const made = send<Check>("/checks", ADMIN, "POST", { ...body, design: "items" });
    expect(made.design).toBe("items");
    expect(made.control).toEqual([]);
    expect(made.metric).toBe(d.metric);
    expect(made.baseline).toMatch(/^\d\d\.\d\d–\d\d\.\d\d, до проверки$/);
    expect(made.hypothesis).toContain("за 4 недели");
    expect(made.hypothesis).not.toContain("{");
    const unmeasured = drafts.find((x) => !x.measured);
    if (unmeasured) {
      const b = { finding_id: unmeasured.finding_id, action: unmeasured.actions[0], control_ids: [], weeks: 4 };
      expect(status(() => send("/checks", ADMIN, "POST", b))).toBe(422);
    }
  });

  it("repeats a check once: then it is no longer repeatable (stage 7 review, frontend p. 6)", () => {
    const bread = get<Check[]>("/checks", ADMIN).find((c) => c.title === "Заказ хлеба по дням недели")!;
    if (!bread.repeatable) return; // the earlier test already repeated it in this session
    send<Check>(`/checks/${bread.id}/repeat`, ADMIN, "POST", { weeks: bread.weeks + 2 });
    expect(get<Check[]>("/checks", ADMIN).find((c) => c.id === bread.id)?.repeatable).toBe(false);
    expect(status(() => send(`/checks/${bread.id}/repeat`, ADMIN, "POST", { weeks: bread.weeks + 4 }))).toBe(422);
  });

  it("refuses a repeat over 12 weeks and of a check it does not have, like the server (TC-EXP-46, 50)", () => {
    const bread = get<Check[]>("/checks", ADMIN).find((c) => c.title === "Заказ хлеба по дням недели")!;
    expect(status(() => send(`/checks/${bread.id}/repeat`, ADMIN, "POST", { weeks: 13 }))).toBe(422);
    expect(status(() => send("/checks/another-networks-check/repeat", ADMIN, "POST", { weeks: 6 }))).toBe(404);
    expect(status(() => send("/checks/another-networks-check/repeat", DIRECTOR, "POST", { weeks: 6 }))).toBe(403);
  });
});
