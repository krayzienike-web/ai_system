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
import { money } from "../lib/format";
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
import {
  demoDigest,
  demoDisagree,
  demoDisagreements,
  digestItems,
} from "./demoDigests";
import { demoNorms } from "./demoNorms";
import { demoUnits } from "./demoUnits";
import type {
  CatalogOption,
  AgentNote,
  ApiFinding,
  ApiTask,
  ChatAnswer,
  Check,
  Digest,
  DisagreeReason,
  Disagreement,
  Freshness,
  FindingBoard,
  ImportBatch,
  Me,
} from "./types";

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
  Math.round(
    (new Date(`${to}T00:00:00Z`).getTime() -
      new Date(`${from}T00:00:00Z`).getTime()) /
      86_400_000,
  );

// ------------------------------------------------------------------ what the prototype's actions changed

const findingPatch = new Map<string, Partial<ApiFinding>>();
/** What the actions did to a finding's work, applied to each viewer's own recorded `work` (the server shows a
 * director no checks, so a director's stage never becomes «checking»). */
interface WorkDelta {
  tasks: number;
  /** Late tasks that stopped being late (a moved deadline): the server recounts `tasks_late` from the tasks. */
  late: number;
  taken: boolean;
  waiting: boolean;
  checking: boolean;
}
const workPatch = new Map<string, WorkDelta>();
const touchWork = (id: string, change: Partial<WorkDelta>) => {
  const w = workPatch.get(id) ?? {
    tasks: 0,
    late: 0,
    taken: false,
    waiting: false,
    checking: false,
  };
  workPatch.set(id, {
    ...w,
    ...change,
    tasks: w.tasks + (change.tasks ?? 0),
    late: w.late + (change.late ?? 0),
  });
};
const taskPatch = new Map<string, Partial<ApiTask>>();
const checkPatch = new Map<string, Partial<Check>>();
const newTasks: ApiTask[] = [];
const newChecks: Check[] = [];
let seq = 0;

/** Every finding / task / check any demo user can see, by id: the pool the actions work on. */
const pool = {
  findings: new Map<string, ApiFinding>(),
  tasks: new Map<string, ApiTask>(),
  checks: new Map<string, Check>(),
};
/** Each finding's story as the HQ's recording has it (key, title): a director's copy may have none. */
const stories = new Map<string, { key: string; title: string }>();
function collect(value: unknown) {
  if (Array.isArray(value)) value.forEach(collect);
  else if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.id === "string") {
      if ("work" in o && "kind" in o) {
        pool.findings.set(
          o.id,
          (pool.findings.get(o.id) ?? o) as unknown as ApiFinding,
        );
        const story = o.story as
          | { key: string; title: string }
          | null
          | undefined;
        if (story) stories.set(o.id, { key: story.key, title: story.title });
      } else if ("checklist_done" in o)
        pool.tasks.set(o.id, o as unknown as ApiTask);
      else if ("hypothesis" in o)
        pool.checks.set(o.id, (pool.checks.get(o.id) ?? o) as unknown as Check);
    }
    Object.values(o).forEach(collect);
  }
}
Object.values(USERS).forEach((u) => collect(u.answers));

const isFinding = (o: Record<string, unknown>) =>
  typeof o.id === "string" && "work" in o && "kind" in o;

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
            work.tasks_late = Math.max(0, work.tasks_late + w.late);
            if (w.taken && work.stage === "new") work.stage = "doing";
            if (v.hq && w.checking)
              Object.assign(work, {
                stage: "checking",
                check_waiting_launch: false,
              });
            else if (v.hq && w.waiting) work.check_waiting_launch = true;
            o.work = work;
          }
          // The server never tells a director who reviewed a finding or why.
          if (!v.hq)
            Object.assign(o, {
              review_note: null,
              review_reason: null,
              reviewed_by_name: null,
            });
        }
        const t = "checklist_done" in o ? taskPatch.get(o.id) : undefined;
        if (t) Object.assign(o, t);
        const c =
          "hypothesis" in o || "progress_text" in o
            ? checkPatch.get(o.id)
            : undefined;
        if (c) Object.assign(o, c);
      }
      Object.values(o).forEach(walk);
    }
  };
  walk(value);
  return value;
}

const takenInDemo = (findingId: string) =>
  workPatch.get(findingId)?.taken ?? false;

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

const restaurants = (v: Viewer) =>
  (v.user.answers["/restaurants"] as {
    id: string;
    code: string;
    name: string;
  }[]) ?? [];
const allRestaurants = () =>
  (USERS["admin@demo.local"]!.answers["/restaurants"] as {
    id: string;
    code: string;
    name: string;
  }[]) ?? [];

const visibleTask = (v: Viewer, t: ApiTask) =>
  v.hq || t.restaurant_id === v.restaurantId;
const reviewOf = (f: ApiFinding) =>
  findingPatch.get(f.id)?.review_status ?? f.review_status;
const checked = (f: ApiFinding) => {
  const r = reviewOf(f);
  return r === null || r === "confirmed";
};

/** «Решить по находке» (ADR 0009) as the server builds it, after what the visitor did: reviewed (also in this
 * session), open, nobody acted on — no task, no check. The recorded order (the server's ranking) first. */
function awaitingOf(v: Viewer): ApiFinding[] {
  const recorded = (
    (v.user.answers["/overview/awaiting"] as ApiFinding[]) ?? []
  ).map((f) => f.id);
  const rank = (f: ApiFinding) =>
    recorded.includes(f.id) ? recorded.indexOf(f.id) : recorded.length;
  return overlay(v, clone([...pool.findings.values()]))
    .filter(
      (f) =>
        checked(f) &&
        f.status === "new" &&
        f.work.stage === "new" &&
        !f.work.check_waiting_launch,
    )
    .sort(
      (a, b) =>
        rank(a) - rank(b) ||
        (money(b.effect_rub_month) ?? 0) - (money(a.effect_rub_month) ?? 0),
    );
}

/** The working list: recorded, plus findings confirmed in this session; minus ones reopened or rejected. */
function findingsOf(v: Viewer): ApiFinding[] {
  const recorded = (v.user.answers["/findings"] as ApiFinding[]) ?? [];
  const ids = new Set(recorded.map((f) => f.id));
  // A director meets a finding once the HQ set a task on their restaurant (ADR 0009): those the recording has,
  // and those the visitor's HQ assigned in this session.
  const tasked = (f: ApiFinding) =>
    newTasks.some(
      (t) => t.finding_id === f.id && t.restaurant_id === v.restaurantId,
    );
  const extra = [...pool.findings.values()].filter(
    (f) =>
      !ids.has(f.id) &&
      checked(f) &&
      f.status !== "dismissed" &&
      (v.hq ||
        (f.restaurant_id !== null &&
          f.restaurant_id === v.restaurantId &&
          tasked(f))),
  );
  const list = overlay(v, clone([...recorded, ...extra])).filter(checked);
  return list.map((f) => ({ ...f, story: storyFor(f, storyScope(v, list)) }));
}

function tasksOf(v: Viewer, late: boolean): ApiTask[] {
  const recorded = (v.user.answers["/tasks"] as ApiTask[]) ?? [];
  // A director's task names its finding only when the director sees it (the server's row-level security):
  // a network-wide finding's task is «from the HQ», without the finding's title or its network sum.
  const seen = v.hq ? null : new Set(findingsOf(v).map((f) => f.id));
  const mine = newTasks
    .filter((t) => visibleTask(v, t))
    .map((t) =>
      seen && t.finding_id && !seen.has(t.finding_id)
        ? {
            ...t,
            finding_title: null,
            finding_effect_rub_month: null,
            source: "Поставлено управляющей компанией",
          }
        : t,
    );
  const all = overlay(v, clone([...recorded, ...mine]));
  return late ? all.filter((t) => t.late) : all;
}

// ------------------------------------------------------------------ the findings list (same rules as overview/service.py: board)

const GROUP_TITLE = {
  problem: "Где теряем",
  opportunity: "Где можно заработать",
  unestimated: "Без оценки в рублях — но важно для точности",
};
const PROCESS_ORDER = [
  "purchasing",
  "receiving",
  "storage",
  "production",
  "writeoffs",
  "inventory",
  "accounting",
  "planning",
];
/** What each finding adds to a sum, as the server counts it (insights/money.py): a story's findings (one cause,
 * docs/12) once — its largest one; a `supplier:` story's are different money and add up. Over the whole set,
 * filtered after (code review of stage 6.5, frontend p. 1). */
const ADDING = "supplier:";
function counted(items: ApiFinding[]): Map<string, number> {
  const out = new Map<string, number>();
  const stories = new Map<string, ApiFinding[]>();
  for (const f of items) {
    const key = storyKey(f);
    if (key && !key.startsWith(ADDING))
      stories.set(key, [...(stories.get(key) ?? []), f]);
    else out.set(f.id, Number(f.effect_rub_month ?? 0));
  }
  for (const members of stories.values()) {
    const largest = members.reduce((a, b) =>
      Number(b.effect_rub_month ?? 0) > Number(a.effect_rub_month ?? 0) ? b : a,
    );
    for (const f of members)
      out.set(f.id, f === largest ? Number(f.effect_rub_month ?? 0) : 0);
  }
  return out;
}
const sum = (
  items: ApiFinding[],
  money: Map<string, number> = counted(items),
) => items.reduce((acc, f) => acc + (money.get(f.id) ?? 0), 0).toFixed(2);

/** A finding's story key: the recording of the HQ (the pool) knows it even where this viewer's has none. */
const storyKey = (f: ApiFinding): string | null =>
  stories.get(f.id)?.key ?? f.story?.key ?? null;
const OPEN = ["new", "in_work", "in_experiment"];

/** Whom a story may name, as the server reads it (row-level security): the HQ — every finding of the network
 * but the rejected ones (also those still awaiting the review); a director — the findings they are shown. */
function storyScope(v: Viewer, shown: ApiFinding[]): ApiFinding[] {
  return v.hq
    ? overlay(v, clone([...pool.findings.values()])).filter(
        (f) => reviewOf(f) !== "rejected",
      )
    : shown;
}

/** The story of a finding as the server builds it for this viewer (insights/visible.py): only the other
 * findings they can see, its sum over the open ones (code review of stage 6.5, frontend p. 2). */
function storyFor(f: ApiFinding, visible: ApiFinding[]): ApiFinding["story"] {
  const key = storyKey(f);
  if (!key) return null;
  const members = visible.filter(
    (m) => storyKey(m) === key && m.status !== "dismissed",
  );
  const others = members.filter((m) => m.id !== f.id);
  if (!others.length) return null;
  const effects = members
    .filter((m) => OPEN.includes(m.status) && m.effect_rub_month !== null)
    .map((m) => Number(m.effect_rub_month));
  const adds = key.startsWith(ADDING);
  const total = effects.length
    ? adds
      ? effects.reduce((a, b) => a + b, 0)
      : Math.max(...effects)
    : null;
  return {
    key,
    title: stories.get(f.id)?.title ?? f.story?.title ?? f.title,
    adds,
    effect_rub_month: total === null ? null : total.toFixed(2),
    findings: others
      .sort(
        (a, b) =>
          (a.module ?? "").localeCompare(b.module ?? "") ||
          a.title.localeCompare(b.title),
      )
      .map((m) => ({
        id: m.id,
        title: m.title,
        module: m.module,
        kind: m.kind,
        effect_rub_month: m.effect_rub_month,
        restaurant_code: m.restaurant_code ?? null,
      })),
  };
}

export function board(scope: ApiFinding[], q: URLSearchParams): FindingBoard {
  const kind = q.get("kind");
  const keep = (f: ApiFinding) =>
    (!q.get("process") || f.process === q.get("process")) &&
    (!q.get("restaurant") ||
      (f.restaurant_id ?? "net") === q.get("restaurant")) &&
    (!q.get("stage") || f.work.stage === q.get("stage")) &&
    (q.get("late") !== "true" || f.work.tasks_late > 0);
  const filtered = scope.filter(keep);
  const money = counted(filtered);
  const shown = (["problem", "opportunity"] as const).filter(
    (k) => !kind || kind === k,
  );
  type Group = FindingBoard["groups"][number];
  const groups: Group[] = shown
    .map((k): Group => {
      const items = filtered.filter(
        (f) => f.kind === k && f.effect_rub_month !== null,
      );
      return {
        key: k,
        title: GROUP_TITLE[k],
        count: items.length,
        total: sum(items, money),
        items,
      };
    })
    .concat([
      ((): Group => {
        const items = filtered.filter(
          (f) =>
            f.effect_rub_month === null && (shown as string[]).includes(f.kind),
        );
        return {
          key: "unestimated" as const,
          title: GROUP_TITLE.unestimated,
          count: items.length,
          total: "0",
          items,
        };
      })(),
    ])
    .filter((g) => g.items.length);
  const stages = ["new", "doing", "checking", "done"];
  return {
    kinds: (["problem", "opportunity"] as const).map((k) => {
      const items = filtered.filter((f) => f.kind === k);
      return { kind: k, count: items.length, total: sum(items, money) };
    }),
    stage_counts: {
      all: scope.length,
      ...Object.fromEntries(
        stages.map((s) => [s, scope.filter((f) => f.work.stage === s).length]),
      ),
    },
    late_count: scope.filter((f) => f.work.tasks_late > 0).length,
    processes: PROCESS_ORDER.filter((p) => scope.some((f) => f.process === p)),
    groups,
    max_effect: Math.max(
      0,
      ...filtered.map((f) => Number(f.effect_rub_month ?? 0)),
    ).toFixed(2),
  };
}

// ------------------------------------------------------------------ actions

function forbid(ok: boolean, message: string) {
  if (!ok) throw new ApiError(403, message);
}

function newTask(
  fields: Partial<ApiTask> &
    Pick<ApiTask, "restaurant_id" | "title" | "due_on">,
): ApiTask {
  seq += 1;
  const place = allRestaurants().find((r) => r.id === fields.restaurant_id);
  const finding = fields.finding_id
    ? pool.findings.get(fields.finding_id)
    : undefined;
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
  findingPatch.set(findingId, {
    ...findingPatch.get(findingId),
    status: status === "new" ? "in_work" : status,
  });
  touchWork(findingId, { tasks: count, taken: true });
}

function createTasks(
  v: Viewer,
  body: {
    title: string;
    due_on: string;
    finding_id?: string;
    restaurant_ids?: string[];
    checklist?: string[];
  },
) {
  const finding = body.finding_id
    ? pool.findings.get(body.finding_id)
    : undefined;
  if (finding && !checked(finding))
    throw new ApiError(
      422,
      "Находка еще не прошла проверку: задачи по ней ставят после подтверждения",
    );
  // A task on a finding is the HQ's decision (ADR 0009), as on the server: an unseen finding is «not found».
  if (!v.hq && finding && !findingsOf(v).some((f) => f.id === finding.id))
    throw new ApiError(404, "Finding not found");
  if (!v.hq) forbid(!finding, "Задачи по находкам ставит управляющая компания");
  if (
    finding?.restaurant_id &&
    body.restaurant_ids &&
    body.restaurant_ids.some((r) => r !== finding.restaurant_id)
  )
    throw new ApiError(
      422,
      "A restaurant's finding can only be assigned to that restaurant",
    );
  const targets = v.hq
    ? (body.restaurant_ids ??
      (finding?.restaurant_id
        ? [finding.restaurant_id]
        : allRestaurants().map((r) => r.id)))
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
      source: finding
        ? null
        : v.hq
          ? "Поставлено управляющей компанией"
          : "Добавлено директором",
    }),
  );
  newTasks.push(...tasks);
  markTaken(body.finding_id, tasks.length);
  return tasks;
}

function taskAction(
  v: Viewer,
  id: string,
  action: string,
  body: Record<string, unknown>,
) {
  const found = pool.tasks.get(id) ?? newTasks.find((t) => t.id === id);
  if (!found || !visibleTask(v, found))
    throw new ApiError(404, "Task not found");
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
  if (task.status === "done")
    throw new ApiError(422, "The task is already done");
  if (action === "start") return patch({ status: "in_progress" });
  if (action === "checklist") {
    const index = Number(body.index);
    if (!Number.isInteger(index) || index < 0 || index >= task.checklist.length)
      throw new ApiError(422, "Нет такого пункта чек-листа");
    const marks = [...task.checklist_done];
    marks[index] = Boolean(body.done);
    return patch({ checklist_done: marks });
  }
  return patch({
    status: "done",
    done_on: TODAY,
    late: false,
    report: String(body.report ?? ""),
    outcome: {
      verdict: "pending",
      effect_rub_month: null,
      text: "Сколько это дало, посчитаем после ближайшей инвентаризации",
      measured_on: null,
    },
  });
}

function checkAction(v: Viewer, id: string, action: string) {
  forbid(v.hq, "Нет доступа к этому действию");
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
    if (check.verdict !== "confirmed")
      throw new ApiError(422, "Тиражируют только то, что сработало");
    if (check.rollout_on)
      throw new ApiError(422, "Изменение уже отправлено во все рестораны");
    const tested = new Set((check.test ?? []).map((p) => p.id));
    const tasks = allRestaurants()
      .filter((r) => !tested.has(r.id))
      .map((r) =>
        newTask({
          restaurant_id: r.id,
          title: check.title,
          due_on: addDays(TODAY, 14),
          finding_id: check.finding_id,
          experiment_id: check.id,
          source: `Проверка «${check.title}»`,
        }),
      );
    newTasks.push(...tasks);
    patch({ rollout_on: TODAY });
    return tasks;
  }
  if (check.status !== "proposed")
    throw new ApiError(422, "The check is not waiting for a decision");
  if (action === "reject") {
    patch({ status: "rejected" });
    return { ...check, status: "rejected" };
  }
  const tasks = (check.test ?? []).map((p) =>
    newTask({
      restaurant_id: p.id,
      title: check.title,
      due_on: check.ends_on,
      finding_id: check.finding_id,
      experiment_id: check.id,
      source: `Проверка «${check.title}»`,
    }),
  );
  newTasks.push(...tasks);
  patch({ status: "running" });
  if (check.finding_id && pool.findings.has(check.finding_id)) {
    findingPatch.set(check.finding_id, {
      ...findingPatch.get(check.finding_id),
      status: "in_experiment",
    });
    touchWork(check.finding_id, { checking: true, taken: true });
  }
  return tasks;
}

type DraftDesign = {
  design: NonNullable<Check["design"]>;
  available: boolean;
  mde_rub_month: string | null;
  mde_by_weeks?: { weeks: number; rub_month: string }[];
  control_products?: string[];
};
const ddmmOf = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
const plural = (n: number, forms: [string, string, string]) => {
  const m10 = n % 10, m100 = n % 100;
  return `${n} ${m10 === 1 && m100 !== 11 ? forms[0] : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? forms[1] : forms[2]}`;
};

/** «Повторить дольше» as the server does it (experiments/service.py: repeat): a new proposed check. */
function repeatCheck(v: Viewer, id: string, weeks: number) {
  forbid(v.hq, "Проверки готовит управляющая компания");
  const all = overlay(
    v,
    clone([...(v.user.answers["/checks"] as Check[]), ...newChecks]),
  );
  const old = all.find((c) => c.id === id);
  if (!old) throw new ApiError(404, "Проверка не найдена");
  if (old.status !== "completed" || old.verdict === "confirmed")
    throw new ApiError(
      422,
      "Повторяют проверку, которая не подтвердила эффект",
    );
  if (!old.finding_id) throw new ApiError(422, "У проверки нет находки");
  if (!(weeks > old.weeks))
    throw new ApiError(422, "Повторная проверка — дольше прежней");
  if (weeks > 12) throw new ApiError(422, "Проверка — не дольше 12 недель");
  return propose(
    v,
    {
      finding_id: old.finding_id,
      action: old.title,
      control_ids: old.control_restaurant_ids,
      weeks,
      design: old.design,
    },
    old,
  );
}

function propose(
  v: Viewer,
  body: {
    finding_id: string;
    action: string;
    control_ids: string[];
    weeks: number;
    design?: Check["design"];
  },
  repeatOf?: Check,
) {
  forbid(v.hq, "Проверки готовит управляющая компания");
  const draft = v.user.answers[
    `/checks/draft?finding_id=${body.finding_id}`
  ] as
    | {
        finding_title: string;
        actions: string[];
        test: { id: string; code: string; name: string };
        candidates: { restaurant_id: string; code: string; name: string }[];
        expected_rub_month: string;
        measured?: boolean;
        metric?: string;
        hypothesis?: string;
        durations?: { weeks: number }[];
        designs?: DraftDesign[];
      }
    | undefined;
  if (!draft) throw new ApiError(422, "Для этой находки проверку не поставить");
  if (openCheck(v, body.finding_id))
    throw new ApiError(422, "По этой находке уже есть проверка");
  if (!draft.actions.includes(body.action) && body.action !== repeatOf?.title)
    throw new ApiError(422, "Выберите меру из находки");
  // the server's rules for the design (experiments/service.py: propose)
  const design = body.design ?? "restaurants";
  const chosen = draft.designs?.find((o) => o.design === design);
  if (!["restaurants", "items", "before_after"].includes(design))
    throw new ApiError(422, "Неизвестный дизайн проверки");
  if (!draft.measured) throw new ApiError(422, "Эту находку замер не считает — поставьте задачу директору");
  if (design === "restaurants" && !body.control_ids.length) throw new ApiError(422, "Выберите рестораны для сравнения");
  const allowed = new Set(draft.candidates.map((c) => c.restaurant_id));
  if (!body.control_ids.every((id) => allowed.has(id)))
    throw new ApiError(422, "Сравнивать можно только с другими ресторанами сети");
  const offered = (draft.durations ?? []).some((o) => o.weeks === body.weeks);
  if (!offered && !(repeatOf && body.weeks <= 12)) throw new ApiError(422, "Недопустимая длительность проверки");
  if (!chosen?.available) throw new ApiError(422, "Этот дизайн для находки не подходит");
  seq += 1;
  const starts = addDays(TODAY, 3);
  const ends = addDays(starts, body.weeks * 7);
  // the period before, as the server fixes it (experiments/design.py: baseline): as long as the check, ≥ 4 weeks
  const beforeDays = Math.max(body.weeks * 7, 28);
  const baseline = `${ddmmOf(addDays(starts, -beforeDays))}–${ddmmOf(addDays(starts, -1))}, до проверки`;
  const measure = body.action[0]!.toLowerCase() + body.action.slice(1);
  const template = draft.hypothesis ?? `Если {action}, показатель находки приблизится к цели за {weeks}.`;
  const hypothesis = template.replace("{action}", measure).replace("{weeks}", plural(body.weeks, ["неделю", "недели", "недель"]));
  const mde = chosen.mde_by_weeks?.find((m) => m.weeks === body.weeks)?.rub_month ?? chosen.mde_rub_month;
  const check: Check = {
    id: `demo-check-${seq}`,
    finding_id: body.finding_id,
    title: body.action,
    hypothesis,
    metric: draft.metric ?? draft.finding_title,
    test_restaurant_ids: [draft.test.id],
    control_restaurant_ids: design === "restaurants" ? body.control_ids : [],
    starts_on: starts,
    ends_on: ends,
    expected_rub_month: draft.expected_rub_month,
    status: "proposed",
    verdict: null,
    effect_rub_month: null,
    ci_low_rub_month: null,
    ci_high_rub_month: null,
    result_text: null,
    baseline,
    weeks: body.weeks,
    progress_text: null,
    rollout_rub_month: null,
    rollout_on: null,
    completed_on: null,
    finding_title: draft.finding_title,
    test: [draft.test],
    control:
      design === "restaurants"
        ? draft.candidates
            .filter((c) => body.control_ids.includes(c.restaurant_id))
            .map((c) => ({ id: c.restaurant_id, code: c.code, name: c.name }))
        : [],
    design,
    measured: true,
    mde_rub_month: mde ?? null,
    measured_on: null,
    control_products: design === "items" ? (chosen.control_products ?? []) : [],
    repeatable: false,
  };
  newChecks.push(check);
  touchWork(body.finding_id, { waiting: true });
  return check;
}

/** «Повторить дольше» possible now, as the server says it (experiments/api.py: checks_out): no confirmed
 * effect, a finding, no open check on it (a repeat made in this session is one), under 12 weeks. */
function repeatableNow<T extends Check>(v: Viewer, c: T): T {
  const possible =
    c.status === "completed" && c.verdict !== "confirmed" && !!c.finding_id && !openCheck(v, c.finding_id) && c.weeks < 12;
  return { ...c, repeatable: possible };
}

/** The finding's check that is waiting for a launch or going on (one at a time, as on the server). */
function openCheck(v: Viewer, findingId: string): Check | undefined {
  const all = overlay(v, clone([...pool.checks.values(), ...newChecks]));
  return all
    .filter(
      (c) =>
        c.finding_id === findingId &&
        (c.status === "proposed" || c.status === "running"),
    )
    .at(-1);
}

function review(
  v: Viewer,
  id: string,
  body: { verdict: string; reason?: string; note?: string },
) {
  forbid(v.hq, "Находки проверяет управляющая компания");
  const f = pool.findings.get(id);
  if (!f) throw new ApiError(404, "Находка не найдена");
  if (body.verdict === "reject" && !body.reason)
    throw new ApiError(
      422,
      "Укажите, что не так: данные, логика расчета или это не проблема",
    );
  if (
    body.verdict === "reject" &&
    (body.reason === "logic" || body.reason === "other") &&
    !body.note?.trim()
  )
    throw new ApiError(
      422,
      "Опишите, что не так, — по этому описанию поправим движок",
    );
  const reopen = body.verdict === "reopen";
  findingPatch.set(id, {
    ...findingPatch.get(id),
    review_status:
      body.verdict === "confirm"
        ? "confirmed"
        : body.verdict === "reject"
          ? "rejected"
          : "pending",
    review_reason:
      body.verdict === "reject"
        ? ((body.reason ?? null) as ApiFinding["review_reason"])
        : null,
    review_note: body.note?.trim() || null,
    reviewed_on: reopen ? null : TODAY,
    reviewed_by_name: reopen ? null : v.me.full_name,
  });
  return overlay(v, clone(f));
}

// ------------------------------------------------------------------ the agents' notes (stage 9)

// The recorded notes, minus those the visitor answered in this tab; the answers do what the server's do.
const answeredNotes = new Map<string, AgentNote>();

function notesOf(v: Viewer): AgentNote[] {
  return ((v.user.answers["/agents/notes"] as AgentNote[] | undefined) ?? []).filter(
    (n) => !answeredNotes.has(n.id),
  );
}

function answerNote(v: Viewer, id: string, answer: string): AgentNote {
  const note = notesOf(v).find((n) => n.id === id);
  if (!note) {
    if (answeredNotes.has(id)) throw new ApiError(409, "По этому сообщению уже решили");
    throw new ApiError(404, "Сообщение не найдено");
  }
  forbid(
    v.admin || (note.audience === "director" && !v.hq),
    "Отвечать на это сообщение может директор ресторана или администратор УК",
  );
  let result: string | null = null;
  if (answer === "accept") {
    if (note.action === "create_task" && note.action_due_on && note.action_title) {
      if (note.action_due_on < TODAY) throw new ApiError(422, "День пересчета уже прошел");
      const [task] = createTasks(v, {
        title: note.action_title,
        due_on: note.action_due_on,
        restaurant_ids: note.restaurant_id ? [note.restaurant_id] : [],
        checklist: note.items.map((line) => `Пересчитать: ${line}`),
      });
      result = task?.id ?? null;
    } else if (note.action === "transfer" && note.action_due_on) {
      const due = note.action_due_on < TODAY ? TODAY : note.action_due_on;
      const made = note.action_tasks.flatMap((t) =>
        createTasks(v, { title: t.title, due_on: due, restaurant_ids: [t.restaurant_id], checklist: t.checklist }),
      );
      result = made[0]?.id ?? null;
    } else if (note.action === "claim") {
      result = null; // «Отправлено»: the HQ sent the letter itself
    } else if (note.action === "move_due" && note.task_id && note.action_due_on) {
      forbid(v.admin, "Срок задачи переносит администратор УК");
      const due = note.action_due_on;
      const current = tasksOf(v, false).find((t) => t.id === note.task_id);
      if (!current) throw new ApiError(422, "Задачи больше нет");
      if (current.status === "done") throw new ApiError(422, "Задача уже выполнена");
      if (due < TODAY) throw new ApiError(422, "Due date is in the past");
      if (current.late && current.finding_id) touchWork(current.finding_id, { late: -1 });
      taskPatch.set(note.task_id, {
        ...taskPatch.get(note.task_id),
        due_on: due,
        days_left: daysBetween(TODAY, due),
        late: false,
      });
      result = note.task_id;
    } else throw new ApiError(422, "Здесь нечего брать в работу: сообщение можно только скрыть");
  }
  const done: AgentNote = {
    ...note,
    status: answer === "accept" ? "accepted" : "dismissed",
    result_task_id: result,
  };
  answeredNotes.set(id, done);
  return done;
}

// ------------------------------------------------------------------ requests

export function demoRequest(
  path: string,
  init: RequestInit,
  token: string | null,
): unknown | Promise<unknown> {
  const method = init.method ?? "GET";
  const body =
    typeof init.body === "string"
      ? (JSON.parse(init.body) as Record<string, unknown>)
      : {};
  if (path === "/auth/login") {
    const key = String(body.email ?? "")
      .trim()
      .toLowerCase();
    if (!USERS[key] || body.password !== DEMO_PASSWORD)
      throw new DemoAuthError("invalid credentials");
    return { access_token: key, token_type: "bearer", must_change_password: false };
  }
  const v = viewer(token);
  const answers = v.user.answers;

  // Data import, norms and engine settings: their own small simulations.
  if (path === "/imports/templates") return DEMO_TEMPLATES;
  if (path === "/imports/freshness")
    return demoFreshness((answers["/imports/freshness"] as Freshness[]) ?? []);
  if (path === "/imports" && method === "POST") {
    const target = (init.body as FormData).get("restaurant_id") || null;
    if (!v.hq && target !== v.restaurantId)
      throw new ApiError(403, "Можно загружать данные только своего ресторана");
    return demoUpload(init.body as FormData);
  }
  const batchId =
    /^\/imports\/([^/]+)\/(match|publish|rollback|reprocess)$/.exec(path)?.[1];
  if (!v.hq && batchId && demoBatchRestaurant(batchId) !== v.restaurantId)
    throw new ApiError(404, "Загрузка не найдена");
  const aliasId = /^\/aliases\/([^/]+)$/.exec(path)?.[1];
  if (!v.hq && aliasId && demoAliasRestaurant(aliasId) !== v.restaurantId)
    throw new ApiError(404, "Соответствие не найдено");
  if (path === "/imports")
    return [
      ...demoBatches(v.restaurantId),
      ...((answers["/imports"] as ImportBatch[]) ?? []),
    ];
  if (path === "/aliases" && method === "GET")
    return demoAliases(v.restaurantId);
  if (aliasId) return demoAliasEdit(aliasId, init);
  const matching = /^\/imports\/([^/]+)\/match$/.exec(path);
  if (matching) return demoMatch(matching[1]!, String(init.body));
  const batchAction = /^\/imports\/([^/]+)\/(publish|rollback|reprocess)$/.exec(
    path,
  );
  if (batchAction)
    return demoBatchAction(
      batchAction[1]!,
      batchAction[2] as "publish" | "rollback" | "reprocess",
    );
  if (path === "/settings/engine") return demoEngineParams(init, v.admin);
  if (path === "/settings/norms") return demoNorms(init, v.admin);
  if (path.startsWith("/settings/units"))
    return demoUnits(path, init, v.admin, (answers["/catalog/product"] as CatalogOption[]) ?? []);
  if (/^\/imports\/[^/]+\/recheck$/.test(path))
    throw new ApiError(422, "Проверить заново можно только файл с ошибками"); // demo files have no unknown units

  // Weekly digests (stage 6).
  const disagreeing = /^\/findings\/([^/]+)\/disagree$/.exec(path);
  if (disagreeing) {
    const place = v.me.restaurant
      ? `${v.me.restaurant.code} · ${v.me.restaurant.name}`
      : null;
    const own = digestItems([answers]).get(disagreeing[1]!);
    return demoDisagree(
      disagreeing[1]!,
      method,
      body,
      { hq: v.hq, restaurant: place },
      own,
    );
  }
  if (path === "/digests/rebuild" && method === "POST") {
    const id = body.restaurant_id
      ? `?restaurant_id=${String(body.restaurant_id)}`
      : "";
    const recorded = answers[`/digests/latest${id}`] as Digest | undefined;
    if (!recorded) throw new ApiError(404, "Сводки пока нет");
    return demoDigest(clone(recorded), takenInDemo, !v.hq);
  }
  // Weeks of a restaurant the viewer may not see: the server answers an empty archive (row-level security).
  if (path.startsWith("/digests/weeks") && !(path in answers)) return [];
  if (path.startsWith("/digests/latest") && answers[path])
    return demoDigest(clone(answers[path] as Digest), takenInDemo, !v.hq);
  if (path.startsWith("/digests/disagreements")) {
    forbid(v.hq, "Несогласия директоров видит управляющая компания");
    const id = new URLSearchParams(path.split("?")[1] ?? "").get(
      "restaurant_id",
    );
    const place = id ? allRestaurants().find((r) => r.id === id) : undefined;
    if (id && !place) throw new ApiError(404, "Ресторан не найден");
    return demoDisagreements(
      clone((answers["/digests/disagreements"] as Disagreement[]) ?? []),
      (answers["/digests/disagree-reasons"] as DisagreeReason[]) ?? [],
      place && `${place.code} · ${place.name}`,
    );
  }

  // Actions.
  if (method === "POST") {
    const noting = /^\/agents\/notes\/([^/]+)\/(accept|dismiss)$/.exec(path);
    if (noting) return answerNote(v, noting[1]!, noting[2]!);
    if (path === "/tasks") return createTasks(v, body as never);
    const task = /^\/tasks\/([^/]+)\/(start|complete|checklist|remind)$/.exec(
      path,
    );
    if (task) return taskAction(v, task[1]!, task[2]!, body);
    if (path === "/checks") return propose(v, body as never);
    const check = /^\/checks\/([^/]+)\/(launch|reject|rollout)$/.exec(path);
    if (check) return checkAction(v, check[1]!, check[2]!);
    const again = /^\/checks\/([^/]+)\/repeat$/.exec(path);
    if (again) return repeatCheck(v, again[1]!, Number(body.weeks));
    const verdict = /^\/findings\/([^/]+)\/review$/.exec(path);
    if (verdict) return review(v, verdict[1]!, body as never);
    if (path === "/analytics/run") {
      forbid(v.admin, "Пересчет запускает администратор");
      // The recorded data does not change in the prototype: the run is over at once, everything stays as it was.
      const now = new Date().toISOString();
      return {
        status: "done",
        trigger: "manual",
        requested_at: now,
        finished_at: now,
        created: 0,
        updated: 0,
        removed: 0,
      };
    }
    if (path === "/chat") {
      const q = String(body.question ?? "");
      const chat = v.user.chat;
      return clone(
        chat[`${String(body.finding_id ?? "")}|${q}`] ??
          chat[q] ??
          chat["Что еще?"],
      );
    }
    throw new ApiError(404, "В прототипе это действие недоступно");
  }

  // Reads.
  const [route = path, query = ""] = path.split("?");
  const q = new URLSearchParams(query);
  if (path === "/findings") return findingsOf(v);
  if (path === "/agents/notes") return notesOf(v);
  // «Решить по находке»: what the visitor already decided on (a task, a check) leaves the list.
  if (path === "/overview/awaiting") {
    forbid(v.hq, "Нет доступа к этому действию");
    return awaitingOf(v);
  }
  // The counters follow the visitor's decisions too: «Ждут решения» = findings to decide + checks + late tasks.
  if (path === "/overview/badges" && v.hq) {
    const proposed = overlay(
      v,
      clone([...(answers["/checks"] as Check[]), ...newChecks]),
    ).filter((c) => c.status === "proposed");
    return {
      ...(answers[path] as object),
      inbox: awaitingOf(v).length + proposed.length + tasksOf(v, true).length,
    };
  }
  // A director's «Задачи» counter: the open tasks, also those made in this tab (as the server counts them).
  if (path === "/overview/badges")
    return {
      ...(answers[path] as object),
      open_tasks: tasksOf(v, false).filter((t) => t.status !== "done").length,
    };
  if (route === "/overview/network" && answers[path]) {
    return {
      ...(overlay(v, clone(answers[path])) as object),
      findings_awaiting: awaitingOf(v).length,
    };
  }
  if (route === "/overview/findings") return board(findingsOf(v), q);
  if (path === "/tasks" || path === "/tasks?late=true")
    return tasksOf(v, path.endsWith("true"));
  const reviewing = /^\/findings\?review=(pending|confirmed|rejected)$/.exec(
    path,
  );
  if (reviewing) {
    forbid(v.hq, "Находки проверяет управляющая компания");
    return overlay(v, clone([...pool.findings.values()])).filter(
      (f) => f.review_status === reviewing[1],
    );
  }
  if (route === "/checks" && v.hq) {
    const all = overlay(
      v,
      clone([...(answers["/checks"] as Check[]), ...newChecks]),
    ).map((c) => repeatableNow(v, c));
    return q.get("status")
      ? all.filter((c) => c.status === q.get("status"))
      : all;
  }
  const check = /^\/checks\/(demo-check-\d+)$/.exec(path);
  if (check && v.hq) {
    const c = newChecks.find((x) => x.id === check[1]);
    if (!c) throw new ApiError(404, "Проверка не найдена");
    return {
      ...clone(c),
      tasks: newTasks.filter((t) => t.experiment_id === c.id),
    };
  }
  const finding = /^\/findings\/([^/?]+)$/.exec(path);
  if (finding) {
    const recorded = answers[path] as Record<string, unknown> | undefined;
    const fromPool = findingsOf(v).find((f) => f.id === finding[1]);
    if ((!recorded || !v.hq) && !fromPool)
      throw new ApiError(404, "Finding not found");
    const detail = overlay(
      v,
      clone(
        recorded ?? {
          ...fromPool,
          tasks: [],
          check: null,
          result_answer: null,
        },
      ),
    ) as Record<string, unknown> & {
      tasks: ApiTask[];
      check: unknown;
    };
    detail.tasks = [
      ...detail.tasks,
      ...newTasks.filter(
        (t) => t.finding_id === finding[1] && visibleTask(v, t),
      ),
    ];
    detail.story = storyFor(
      detail as unknown as ApiFinding,
      storyScope(v, findingsOf(v)),
    );
    const started = v.hq
      ? newChecks.filter((c) => c.finding_id === finding[1]).at(-1)
      : undefined;
    if (started) {
      const {
        id,
        title,
        status,
        verdict,
        effect_rub_month,
        expected_rub_month,
        starts_on,
        ends_on,
        progress_text,
      } = started;
      detail.check = {
        id,
        title,
        status,
        verdict,
        effect_rub_month,
        expected_rub_month,
        starts_on,
        ends_on,
        progress_text,
      };
    }
    return detail;
  }
  const recordedCheck = /^\/checks\/([^/?]+)$/.exec(path);
  if (recordedCheck && answers[path]) {
    const detail = repeatableNow(v, overlay(v, clone(answers[path])) as Check) as Check & { tasks: ApiTask[] };
    detail.tasks = [
      ...detail.tasks,
      ...newTasks.filter((t) => t.experiment_id === recordedCheck[1]),
    ];
    return detail;
  }
  if (path === "/restaurants") return restaurants(v);
  if (path === "/auth/me") return v.me;
  // «Документы» follow the card: a director's finding sent back to the check takes its documents with it.
  const sourcesOf = /^\/findings\/([^/?]+)\/sources$/.exec(path);
  if (sourcesOf && !v.hq && !findingsOf(v).some((f) => f.id === sourcesOf[1]))
    throw new ApiError(404, "Finding not found");
  // The prototype has no assistant (ADR 0007): its blocks stay hidden whatever a recording says.
  if (path === "/overview/context")
    return {
      ...(overlay(v, clone(answers[path])) as object),
      assistant: false,
    };
  if (path in answers) return overlay(v, clone(answers[path]));
  // Answers that depend on the viewer: forbidden for a director, missing otherwise.
  // (another restaurant's page is «not found», as on the server).
  const hqOnly =
    route === "/overview/restaurants" ||
    route.endsWith("/verification") ||
    ["/overview/network", "/reports", "/checks"].some(
      (p) => route === p || route.startsWith(`${p}/`),
    );
  if (!v.hq && hqOnly) throw new ApiError(403, "Нет доступа к этому действию");
  if (
    (route === "/overview/network" || route === "/reports/head") &&
    q.has("date_from")
  )
    throw new ApiError(
      422,
      "В прототипе доступны только готовые периоды: неделя, месяц, квартал",
    );
  throw new ApiError(404, "Не найдено");
}
