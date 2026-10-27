// Standalone prototype (VITE_DEMO=1): no backend, the screens get the answers the API gave on the demo network
// (ADR 0007). `demo/snapshot.json` is recorded by `make demo-snapshot` (backend `app/demo/snapshot.py`).
//
// What this file does, and nothing more:
// - replays the recorded answers of the signed-in demo user;
// - simulates actions (tasks, checklists, checks, review verdicts): the object acted upon changes, totals stay as
//   the server computed them when the snapshot was recorded;
// - mirrors the server's access rules for those actions (a director cannot review, launch, see other restaurants).
// The findings list's filters are applied here to the recorded list; `demo.test.ts` checks them against the
// server's own answers for the recorded filter variants.
import { ApiError } from "./client";
import snapshot from "./demo/snapshot.json";
import { demoEngineParams } from "./demoEngine";
import {
  DEMO_TEMPLATES,
  demoAliasEdit,
  demoAliasRestaurant,
  demoAliases,
  demoBatchAction,
  demoBatchRestaurant,
  demoBatches,
  demoFreshness,
  demoMatch,
  demoUpload,
} from "./demoImports";
import { demoNorms } from "./demoNorms";
import type { ApiFinding, ApiTask, ChatAnswer, Check, Freshness, FindingBoard, ImportBatch, Me } from "./types";

export const DEMO_PASSWORD = snapshot.password;

interface Recorded {
  me: Me;
  answers: Record<string, unknown>;
  chat: Record<string, ChatAnswer>;
}
const USERS = snapshot.users as unknown as Record<string, Recorded>;
const TODAY = snapshot.recorded_for;

export class DemoAuthError extends Error {}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
const daysBetween = (from: string, to: string) =>
  Math.round((new Date(`${to}T00:00:00Z`).getTime() - new Date(`${from}T00:00:00Z`).getTime()) / 86_400_000);

// ------------------------------------------------------------------ what the prototype's actions changed

const findingPatch = new Map<string, Partial<ApiFinding>>();
/** What the actions did to a finding's work, applied to each viewer's own recorded `work` (the server shows a
 * director no checks, so a director's stage never becomes «checking»). */
interface WorkDelta {
  tasks: number;
  taken: boolean;
  waiting: boolean;
  checking: boolean;
}
const workPatch = new Map<string, WorkDelta>();
const touchWork = (id: string, change: Partial<WorkDelta>) => {
  const w = workPatch.get(id) ?? { tasks: 0, taken: false, waiting: false, checking: false };
  workPatch.set(id, { ...w, ...change, tasks: w.tasks + (change.tasks ?? 0) });
};
const taskPatch = new Map<string, Partial<ApiTask>>();
const checkPatch = new Map<string, Partial<Check>>();
const newTasks: ApiTask[] = [];
const newChecks: Check[] = [];
let seq = 0;

/** Every finding / task / check any demo user can see, by id: the pool the actions work on. */
const pool = { findings: new Map<string, ApiFinding>(), tasks: new Map<string, ApiTask>(), checks: new Map<string, Check>() };
function collect(value: unknown) {
  if (Array.isArray(value)) value.forEach(collect);
  else if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.id === "string") {
      if ("work" in o && "kind" in o) pool.findings.set(o.id, (pool.findings.get(o.id) ?? o) as unknown as ApiFinding);
      else if ("checklist_done" in o) pool.tasks.set(o.id, o as unknown as ApiTask);
      else if ("hypothesis" in o) pool.checks.set(o.id, (pool.checks.get(o.id) ?? o) as unknown as Check);
    }
    Object.values(o).forEach(collect);
  }
}
Object.values(USERS).forEach((u) => collect(u.answers));

const isFinding = (o: Record<string, unknown>) => typeof o.id === "string" && "work" in o && "kind" in o;

/** Applies the actions' changes to every finding, task and check inside an answer, as `v` would see them. */
function overlay<T>(v: Viewer, value: T): T {
  const walk = (x: unknown) => {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") {
      const o = x as Record<string, unknown>;
      if (typeof o.id === "string") {
        if (isFinding(o)) {
          Object.assign(o, findingPatch.get(o.id) ?? {});
          const w = workPatch.get(o.id);
          if (w) {
            const work = { ...(o.work as ApiFinding["work"]) };
            work.tasks_total += w.tasks;
            if (w.taken && work.stage === "new") work.stage = "doing";
            if (v.hq && w.checking) Object.assign(work, { stage: "checking", check_waiting_launch: false });
            else if (v.hq && w.waiting) work.check_waiting_launch = true;
            o.work = work;
          }
          // The server never tells a director who reviewed a finding or why.
          if (!v.hq) Object.assign(o, { review_note: null, review_reason: null, reviewed_by_name: null });
        }
        const t = "checklist_done" in o ? taskPatch.get(o.id) : undefined;
        if (t) Object.assign(o, t);
        const c = "hypothesis" in o || "progress_text" in o ? checkPatch.get(o.id) : undefined;
        if (c) Object.assign(o, c);
      }
      Object.values(o).forEach(walk);
      // A restaurant's «what to do» cards are findings nobody has taken yet (overview/service.py).
      if (Array.isArray(o.actions) && o.actions.some((a) => a && typeof a === "object" && isFinding(a as Record<string, unknown>)))
        o.actions = (o.actions as ApiFinding[]).filter((a) => a.work.stage === "new");
    }
  };
  walk(value);
  return value;
}

// ------------------------------------------------------------------ the viewer

function viewer(token: string | null) {
  const user = token ? USERS[token] : undefined;
  if (!user) throw new DemoAuthError("not authenticated");
  const role = user.me.role;
  return {
    user,
    me: user.me,
    restaurantId: user.me.restaurant?.id ?? null,
    hq: role !== "restaurant_director",
    admin: role === "hq_admin",
  };
}
type Viewer = ReturnType<typeof viewer>;

const restaurants = (v: Viewer) => (v.user.answers["/restaurants"] as { id: string; code: string; name: string }[]) ?? [];
const allRestaurants = () => (USERS["admin@demo.local"]!.answers["/restaurants"] as { id: string; code: string; name: string }[]) ?? [];

const visibleTask = (v: Viewer, t: ApiTask) => v.hq || t.restaurant_id === v.restaurantId;
const reviewOf = (f: ApiFinding) => findingPatch.get(f.id)?.review_status ?? f.review_status;
const checked = (f: ApiFinding) => {
  const r = reviewOf(f);
  return r === null || r === "confirmed";
};

/** The working list: recorded, plus findings confirmed in this session; minus ones reopened or rejected. */
function findingsOf(v: Viewer): ApiFinding[] {
  const recorded = (v.user.answers["/findings"] as ApiFinding[]) ?? [];
  const ids = new Set(recorded.map((f) => f.id));
  const extra = [...pool.findings.values()].filter(
    (f) => !ids.has(f.id) && checked(f) && f.status !== "dismissed" && (v.hq || (f.restaurant_id !== null && f.restaurant_id === v.restaurantId)),
  );
  return overlay(v, clone([...recorded, ...extra])).filter(checked);
}

function tasksOf(v: Viewer, late: boolean): ApiTask[] {
  const recorded = (v.user.answers["/tasks"] as ApiTask[]) ?? [];
  const all = overlay(v, clone([...recorded, ...newTasks.filter((t) => visibleTask(v, t))]));
  return late ? all.filter((t) => t.late) : all;
}

// ------------------------------------------------------------------ the findings list (same rules as overview/service.py: board)

const GROUP_TITLE = { problem: "Где теряем", opportunity: "Где можно заработать", unestimated: "Без оценки в рублях — но важно для точности" };
const PROCESS_ORDER = ["purchasing", "receiving", "storage", "production", "writeoffs", "inventory", "accounting", "planning"];
const sum = (items: ApiFinding[]) => items.reduce((acc, f) => acc + Number(f.effect_rub_month ?? 0), 0).toFixed(2);

export function board(scope: ApiFinding[], q: URLSearchParams): FindingBoard {
  const kind = q.get("kind");
  const keep = (f: ApiFinding) =>
    (!q.get("process") || f.process === q.get("process")) &&
    (!q.get("restaurant") || (f.restaurant_id ?? "net") === q.get("restaurant")) &&
    (!q.get("stage") || f.work.stage === q.get("stage")) &&
    (q.get("late") !== "true" || f.work.tasks_late > 0);
  const filtered = scope.filter(keep);
  const shown = (["problem", "opportunity"] as const).filter((k) => !kind || kind === k);
  type Group = FindingBoard["groups"][number];
  const groups: Group[] = shown
    .map((k): Group => {
      const items = filtered.filter((f) => f.kind === k && f.effect_rub_month !== null);
      return { key: k, title: GROUP_TITLE[k], count: items.length, total: sum(items), items };
    })
    .concat([
      ((): Group => {
        const items = filtered.filter((f) => f.effect_rub_month === null && (shown as string[]).includes(f.kind));
        return { key: "unestimated" as const, title: GROUP_TITLE.unestimated, count: items.length, total: "0", items };
      })(),
    ])
    .filter((g) => g.items.length);
  const stages = ["new", "doing", "checking", "done"];
  return {
    kinds: (["problem", "opportunity"] as const).map((k) => {
      const items = filtered.filter((f) => f.kind === k);
      return { kind: k, count: items.length, total: sum(items) };
    }),
    stage_counts: { all: scope.length, ...Object.fromEntries(stages.map((s) => [s, scope.filter((f) => f.work.stage === s).length])) },
    late_count: scope.filter((f) => f.work.tasks_late > 0).length,
    processes: PROCESS_ORDER.filter((p) => scope.some((f) => f.process === p)),
    groups,
    max_effect: Math.max(0, ...filtered.map((f) => Number(f.effect_rub_month ?? 0))).toFixed(2),
  };
}

// ------------------------------------------------------------------ actions

function forbid(ok: boolean, message: string) {
  if (!ok) throw new ApiError(403, message);
}

function newTask(fields: Partial<ApiTask> & Pick<ApiTask, "restaurant_id" | "title" | "due_on">): ApiTask {
  seq += 1;
  const place = allRestaurants().find((r) => r.id === fields.restaurant_id);
  const finding = fields.finding_id ? pool.findings.get(fields.finding_id) : undefined;
  return {
    id: `demo-task-${seq}`,
    finding_id: null,
    experiment_id: null,
    checklist: [],
    checklist_done: [],
    assigned_by: "hq",
    created_on: TODAY,
    status: "assigned",
    late: false,
    days_left: daysBetween(TODAY, fields.due_on),
    done_on: null,
    report: null,
    outcome: null,
    reminded_on: null,
    source: null,
    finding_title: finding?.title ?? null,
    finding_effect_rub_month: finding?.effect_rub_month ?? null,
    restaurant_code: place?.code ?? null,
    restaurant_name: place?.name ?? null,
    ...fields,
  };
}

function markTaken(findingId: string | null | undefined, count: number) {
  if (!findingId) return;
  const f = pool.findings.get(findingId);
  if (!f) return;
  const status = findingPatch.get(findingId)?.status ?? f.status;
  findingPatch.set(findingId, { ...findingPatch.get(findingId), status: status === "new" ? "in_work" : status });
  touchWork(findingId, { tasks: count, taken: true });
}

function createTasks(v: Viewer, body: { title: string; due_on: string; finding_id?: string; restaurant_ids?: string[]; checklist?: string[] }) {
  const finding = body.finding_id ? pool.findings.get(body.finding_id) : undefined;
  if (finding && !checked(finding)) throw new ApiError(422, "Находка еще не прошла проверку: задачи по ней ставят после подтверждения");
  if (!v.hq) forbid(!finding || finding.restaurant_id === v.restaurantId, "Задачи ставят только своему ресторану");
  const targets = v.hq
    ? (body.restaurant_ids ?? (finding?.restaurant_id ? [finding.restaurant_id] : allRestaurants().map((r) => r.id)))
    : [v.restaurantId!];
  if (v.hq) forbid(v.admin, "Задачи ставит администратор управляющей компании");
  const checklist = body.checklist ?? [];
  const tasks = targets.map((rid) =>
    newTask({
      restaurant_id: rid,
      title: body.title,
      due_on: body.due_on,
      finding_id: body.finding_id ?? null,
      checklist,
      checklist_done: checklist.map(() => false),
      assigned_by: v.hq ? "hq" : "director",
      source: finding ? null : v.hq ? "Поставлено управляющей компанией" : "Добавлено директором",
    }),
  );
  newTasks.push(...tasks);
  markTaken(body.finding_id, tasks.length);
  return tasks;
}

function taskAction(v: Viewer, id: string, action: string, body: Record<string, unknown>) {
  const found = pool.tasks.get(id) ?? newTasks.find((t) => t.id === id);
  if (!found || !visibleTask(v, found)) throw new ApiError(404, "Task not found");
  const task = overlay(v, clone(found));
  const patch = (p: Partial<ApiTask>) => {
    const created = newTasks.find((t) => t.id === id);
    if (created) Object.assign(created, p);
    else taskPatch.set(id, { ...taskPatch.get(id), ...p });
    return { ...task, ...p };
  };
  if (action === "remind") {
    forbid(v.admin, "Directors are reminded by the HQ admin");
    if (!task.late) throw new ApiError(422, "The task is not overdue");
    return patch({ reminded_on: TODAY });
  }
  forbid(!v.hq, "Tasks are executed by the restaurant's director");
  if (task.status === "done") throw new ApiError(422, "The task is already done");
  if (action === "start") return patch({ status: "in_progress" });
  if (action === "checklist") {
    const index = Number(body.index);
    if (!Number.isInteger(index) || index < 0 || index >= task.checklist.length) throw new ApiError(422, "Нет такого пункта чек-листа");
    const marks = [...task.checklist_done];
    marks[index] = Boolean(body.done);
    return patch({ checklist_done: marks });
  }
  return patch({
    status: "done",
    done_on: TODAY,
    late: false,
    report: String(body.report ?? ""),
    outcome: { verdict: "pending", effect_rub_month: null, text: "Сколько это дало, посчитаем после ближайшей инвентаризации", measured_on: null },
  });
}

function checkAction(v: Viewer, id: string, action: string) {
  forbid(v.hq, "Forbidden");
  forbid(v.admin, "Only HQ admins launch checks");
  const found = pool.checks.get(id) ?? newChecks.find((c) => c.id === id);
  if (!found) throw new ApiError(404, "Проверка не найдена");
  const check = overlay(v, clone(found));
  const patch = (p: Partial<Check>) => {
    const created = newChecks.find((c) => c.id === id);
    if (created) Object.assign(created, p);
    else checkPatch.set(id, { ...checkPatch.get(id), ...p });
  };
  if (action === "rollout") {
    if (check.verdict !== "confirmed") throw new ApiError(422, "Тиражируют только то, что сработало");
    if (check.rollout_on) throw new ApiError(422, "Изменение уже отправлено во все рестораны");
    const tested = new Set((check.test ?? []).map((p) => p.id));
    const tasks = allRestaurants()
      .filter((r) => !tested.has(r.id))
      .map((r) => newTask({ restaurant_id: r.id, title: check.title, due_on: addDays(TODAY, 14), finding_id: check.finding_id, experiment_id: check.id, source: `Проверка «${check.title}»` }));
    newTasks.push(...tasks);
    patch({ rollout_on: TODAY });
    return tasks;
  }
  if (check.status !== "proposed") throw new ApiError(422, "The check is not waiting for a decision");
  if (action === "reject") {
    patch({ status: "rejected" });
    return { ...check, status: "rejected" };
  }
  const tasks = (check.test ?? []).map((p) =>
    newTask({ restaurant_id: p.id, title: check.title, due_on: check.ends_on, finding_id: check.finding_id, experiment_id: check.id, source: `Проверка «${check.title}»` }),
  );
  newTasks.push(...tasks);
  patch({ status: "running" });
  if (check.finding_id && pool.findings.has(check.finding_id)) {
    findingPatch.set(check.finding_id, { ...findingPatch.get(check.finding_id), status: "in_experiment" });
    touchWork(check.finding_id, { checking: true, taken: true });
  }
  return tasks;
}

function propose(v: Viewer, body: { finding_id: string; action: string; control_ids: string[]; weeks: number }) {
  forbid(v.hq, "Проверки готовит управляющая компания");
  const draft = v.user.answers[`/checks/draft?finding_id=${body.finding_id}`] as
    | { finding_title: string; actions: string[]; test: { id: string; code: string; name: string }; candidates: { restaurant_id: string; code: string; name: string }[]; expected_rub_month: string }
    | undefined;
  if (!draft) throw new ApiError(422, "Для этой находки проверку не поставить");
  if (openCheck(v, body.finding_id)) throw new ApiError(422, "По этой находке уже есть проверка");
  if (!draft.actions.includes(body.action)) throw new ApiError(422, "Выберите меру из находки");
  seq += 1;
  const starts = addDays(TODAY, 3);
  const check: Check = {
    id: `demo-check-${seq}`,
    finding_id: body.finding_id,
    title: body.action,
    hypothesis: `Если ${body.action[0]!.toLowerCase()}${body.action.slice(1)}, показатель находки приблизится к уровню сети.`,
    metric: draft.finding_title,
    test_restaurant_ids: [draft.test.id],
    control_restaurant_ids: body.control_ids,
    starts_on: starts,
    ends_on: addDays(starts, body.weeks * 7),
    expected_rub_month: draft.expected_rub_month,
    status: "proposed",
    verdict: null,
    effect_rub_month: null,
    ci_low_rub_month: null,
    ci_high_rub_month: null,
    result_text: null,
    baseline: `${body.weeks} недели до проверки`,
    weeks: body.weeks,
    progress_text: null,
    rollout_rub_month: null,
    rollout_on: null,
    completed_on: null,
    finding_title: draft.finding_title,
    test: [draft.test],
    control: draft.candidates.filter((c) => body.control_ids.includes(c.restaurant_id)).map((c) => ({ id: c.restaurant_id, code: c.code, name: c.name })),
  };
  newChecks.push(check);
  touchWork(body.finding_id, { waiting: true });
  return check;
}

/** The finding's check that is waiting for a launch or going on (one at a time, as on the server). */
function openCheck(v: Viewer, findingId: string): Check | undefined {
  const all = overlay(v, clone([...pool.checks.values(), ...newChecks]));
  return all.filter((c) => c.finding_id === findingId && (c.status === "proposed" || c.status === "running")).at(-1);
}

function review(v: Viewer, id: string, body: { verdict: string; reason?: string; note?: string }) {
  forbid(v.hq, "Находки проверяет управляющая компания");
  const f = pool.findings.get(id);
  if (!f) throw new ApiError(404, "Находка не найдена");
  if (body.verdict === "reject" && !body.reason) throw new ApiError(422, "Укажите, что не так: данные, логика расчета или это не проблема");
  if (body.verdict === "reject" && (body.reason === "logic" || body.reason === "other") && !body.note?.trim())
    throw new ApiError(422, "Опишите, что не так, — по этому описанию поправим движок");
  const reopen = body.verdict === "reopen";
  findingPatch.set(id, {
    ...findingPatch.get(id),
    review_status: body.verdict === "confirm" ? "confirmed" : body.verdict === "reject" ? "rejected" : "pending",
    review_reason: body.verdict === "reject" ? ((body.reason ?? null) as ApiFinding["review_reason"]) : null,
    review_note: body.note?.trim() || null,
    reviewed_on: reopen ? null : TODAY,
    reviewed_by_name: reopen ? null : v.me.full_name,
  });
  return overlay(v, clone(f));
}

// ------------------------------------------------------------------ requests

export function demoRequest(path: string, init: RequestInit, token: string | null): unknown | Promise<unknown> {
  const method = init.method ?? "GET";
  const body = typeof init.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : {};
  if (path === "/auth/login") {
    const key = String(body.email ?? "").trim().toLowerCase();
    if (!USERS[key] || body.password !== DEMO_PASSWORD) throw new DemoAuthError("invalid credentials");
    return { access_token: key, refresh_token: key, token_type: "bearer" };
  }
  const v = viewer(token);
  const answers = v.user.answers;

  // Data import, norms and engine settings: their own small simulations.
  if (path === "/imports/templates") return DEMO_TEMPLATES;
  if (path === "/imports/freshness") return demoFreshness((answers["/imports/freshness"] as Freshness[]) ?? []);
  if (path === "/imports" && method === "POST") {
    const target = (init.body as FormData).get("restaurant_id") || null;
    if (!v.hq && target !== v.restaurantId) throw new ApiError(403, "Можно загружать данные только своего ресторана");
    return demoUpload(init.body as FormData);
  }
  const batchId = /^\/imports\/([^/]+)\/(match|publish|rollback|reprocess)$/.exec(path)?.[1];
  if (!v.hq && batchId && demoBatchRestaurant(batchId) !== v.restaurantId) throw new ApiError(404, "Загрузка не найдена");
  const aliasId = /^\/aliases\/([^/]+)$/.exec(path)?.[1];
  if (!v.hq && aliasId && demoAliasRestaurant(aliasId) !== v.restaurantId) throw new ApiError(404, "Соответствие не найдено");
  if (path === "/imports") return [...demoBatches(v.restaurantId), ...((answers["/imports"] as ImportBatch[]) ?? [])];
  if (path === "/aliases" && method === "GET") return demoAliases(v.restaurantId);
  if (aliasId) return demoAliasEdit(aliasId, init);
  const matching = /^\/imports\/([^/]+)\/match$/.exec(path);
  if (matching) return demoMatch(matching[1]!, String(init.body));
  const batchAction = /^\/imports\/([^/]+)\/(publish|rollback|reprocess)$/.exec(path);
  if (batchAction) return demoBatchAction(batchAction[1]!, batchAction[2] as "publish" | "rollback" | "reprocess");
  if (path === "/settings/engine") return demoEngineParams(init, v.admin);
  if (path === "/settings/norms") return demoNorms(init, v.admin);

  // Actions.
  if (method === "POST") {
    if (path === "/tasks") return createTasks(v, body as never);
    const task = /^\/tasks\/([^/]+)\/(start|complete|checklist|remind)$/.exec(path);
    if (task) return taskAction(v, task[1]!, task[2]!, body);
    if (path === "/checks") return propose(v, body as never);
    const check = /^\/checks\/([^/]+)\/(launch|reject|rollout)$/.exec(path);
    if (check) return checkAction(v, check[1]!, check[2]!);
    const verdict = /^\/findings\/([^/]+)\/review$/.exec(path);
    if (verdict) return review(v, verdict[1]!, body as never);
    if (path === "/analytics/run") {
      forbid(v.admin, "Пересчет запускает администратор");
      // The recorded data does not change in the prototype: the run is over at once, everything stays as it was.
      const now = new Date().toISOString();
      const n = pool.findings.size;
      return { status: "done", trigger: "manual", requested_at: now, finished_at: now, created: 0, updated: n, removed: 0 };
    }
    if (path === "/chat") {
      const q = String(body.question ?? "");
      const chat = v.user.chat;
      return clone(chat[`${String(body.finding_id ?? "")}|${q}`] ?? chat[q] ?? chat["Что еще?"]);
    }
    throw new ApiError(404, `Demo mode: ${path} is not available`);
  }

  // Reads.
  const [route = path, query = ""] = path.split("?");
  const q = new URLSearchParams(query);
  if (path === "/findings") return findingsOf(v);
  if (route === "/overview/findings") return board(findingsOf(v), q);
  if (path === "/tasks" || path === "/tasks?late=true") return tasksOf(v, path.endsWith("true"));
  const reviewing = /^\/findings\?review=(pending|confirmed|rejected)$/.exec(path);
  if (reviewing) {
    forbid(v.hq, "Находки проверяет управляющая компания");
    return overlay(v, clone([...pool.findings.values()])).filter((f) => f.review_status === reviewing[1]);
  }
  if (route === "/checks" && v.hq) {
    const all = overlay(v, clone([...(answers["/checks"] as Check[]), ...newChecks]));
    return q.get("status") ? all.filter((c) => c.status === q.get("status")) : all;
  }
  const check = /^\/checks\/(demo-check-\d+)$/.exec(path);
  if (check && v.hq) {
    const c = newChecks.find((x) => x.id === check[1]);
    if (!c) throw new ApiError(404, "Проверка не найдена");
    return { ...clone(c), tasks: newTasks.filter((t) => t.experiment_id === c.id) };
  }
  const finding = /^\/findings\/([^/?]+)$/.exec(path);
  if (finding) {
    const recorded = answers[path] as Record<string, unknown> | undefined;
    const fromPool = findingsOf(v).find((f) => f.id === finding[1]);
    if ((!recorded || !v.hq) && !fromPool) throw new ApiError(404, "Finding not found");
    const detail = overlay(v, clone(recorded ?? { ...fromPool, tasks: [], check: null, result_answer: null })) as Record<string, unknown> & {
      tasks: ApiTask[];
      check: unknown;
    };
    detail.tasks = [...detail.tasks, ...newTasks.filter((t) => t.finding_id === finding[1] && visibleTask(v, t))];
    const started = v.hq ? newChecks.filter((c) => c.finding_id === finding[1]).at(-1) : undefined;
    if (started) {
      const { id, title, status, verdict, effect_rub_month, expected_rub_month, starts_on, ends_on, progress_text } = started;
      detail.check = { id, title, status, verdict, effect_rub_month, expected_rub_month, starts_on, ends_on, progress_text };
    }
    return detail;
  }
  const recordedCheck = /^\/checks\/([^/?]+)$/.exec(path);
  if (recordedCheck && answers[path]) {
    const detail = overlay(v, clone(answers[path])) as { tasks: ApiTask[] };
    detail.tasks = [...detail.tasks, ...newTasks.filter((t) => t.experiment_id === recordedCheck[1])];
    return detail;
  }
  if (path === "/restaurants") return restaurants(v);
  if (path === "/auth/me") return v.me;
  if (path in answers) return overlay(v, clone(answers[path]));
  // Answers that depend on the viewer: forbidden for a director, missing otherwise.
  // (another restaurant's page is «not found», as on the server).
  const hqOnly =
    route === "/overview/restaurants" ||
    route.endsWith("/verification") ||
    ["/overview/network", "/reports", "/checks"].some((p) => route === p || route.startsWith(`${p}/`));
  if (!v.hq && hqOnly) throw new ApiError(403, "Forbidden");
  if ((route === "/overview/network" || route === "/reports/head") && q.has("date_from"))
    throw new ApiError(422, "В прототипе доступны только готовые периоды: неделя, месяц, квартал");
  throw new ApiError(404, "Не найдено");
}
