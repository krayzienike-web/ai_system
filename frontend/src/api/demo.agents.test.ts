// «Помощник» in the prototype (stage 9): the answers follow the server's rules (agents/service.py) and the
// counters follow the answers (frontend review of stage 9, pp. 1–3, 10).
import { describe, expect, it } from "vitest";

import { askRange, mayAnswer } from "../app/agents/AgentNotes";
import { ApiError } from "./client";
import { demoRequest } from "./demo";
import type { AgentNote, ApiFinding, ApiTask } from "./types";

const ADMIN = "admin@demo.local";
const ANALYST = "analyst@demo.local";
const DIRECTOR = "director1@demo.local"; // R01

const get = <T>(path: string, token: string) => demoRequest(path, {}, token) as T;
const post = <T>(path: string, token: string) => demoRequest(path, { method: "POST" }, token) as T;
const status = (fn: () => unknown) => {
  try {
    fn();
  } catch (e) {
    return e instanceof ApiError ? e.status : "not an ApiError";
  }
  return 200;
};
const note = (token: string, agent: AgentNote["agent"]) =>
  get<AgentNote[]>("/agents/notes", token).find((n) => n.agent === agent)!;

describe("the agents' notes in the prototype", () => {
  it("lets the analyst read but not answer, and a director only their own notes", () => {
    const stuck = note(ANALYST, "task_stuck");
    expect(stuck).toBeDefined();
    expect(status(() => post(`/agents/notes/${stuck.id}/accept`, ANALYST))).toBe(403);
    expect(status(() => post(`/agents/notes/${stuck.id}/dismiss`, ANALYST))).toBe(403);
    expect(get<AgentNote[]>("/agents/notes", DIRECTOR).map((n) => n.agent)).toEqual(["inventory_prep"]);
    expect(status(() => post(`/agents/notes/${stuck.id}/accept`, DIRECTOR))).toBe(404);
  });

  it("refuses «Создать задачу» on a note that proposes nothing", () => {
    const check = note(ADMIN, "data_check");
    expect(check.action).toBeNull();
    expect(status(() => post(`/agents/notes/${check.id}/accept`, ADMIN))).toBe(422);
  });

  it("makes the director's task from the list and counts it in «Задачи»; a second answer is 409", () => {
    const before = get<{ open_tasks: number }>("/overview/badges", DIRECTOR).open_tasks;
    const prep = note(DIRECTOR, "inventory_prep");
    const answer = post<AgentNote>(`/agents/notes/${prep.id}/accept`, DIRECTOR);
    expect(answer.status).toBe("accepted");
    const task = get<ApiTask[]>("/tasks", DIRECTOR).find((t) => t.id === answer.result_task_id)!;
    expect(task.title).toBe(prep.action_title);
    expect(task.checklist[0]).toBe(`Пересчитать: ${prep.items[0]}`);
    expect(get<{ open_tasks: number }>("/overview/badges", DIRECTOR).open_tasks).toBe(before + 1);
    expect(status(() => post(`/agents/notes/${prep.id}/accept`, DIRECTOR))).toBe(409);
    expect(get<AgentNote[]>("/agents/notes", DIRECTOR)).toEqual([]);
  });

  it("moves a stuck task's deadline: the task, its finding and «Ждут решения» are no longer late", () => {
    const stuck = note(ADMIN, "task_stuck");
    const late = () => get<ApiTask[]>("/tasks?late=true", ADMIN).map((t) => t.id);
    const lateFindings = () =>
      get<{ late_count: number }>("/overview/findings?late=true", ADMIN).late_count;
    const inbox = get<{ inbox: number }>("/overview/badges", ADMIN).inbox;
    const findingsBefore = lateFindings();
    expect(late()).toContain(stuck.task_id);
    post(`/agents/notes/${stuck.id}/accept`, ADMIN);
    expect(late()).not.toContain(stuck.task_id);
    const task = get<ApiTask[]>("/tasks", ADMIN).find((t) => t.id === stuck.task_id)!;
    expect(task.due_on).toBe(stuck.action_due_on);
    expect(get<{ inbox: number }>("/overview/badges", ADMIN).inbox).toBe(inbox - 1);
    if (task.finding_id) {
      expect(lateFindings()).toBe(findingsBefore - 1);
      const f = get<ApiFinding[]>("/findings", ADMIN).find((x) => x.id === task.finding_id)!;
      expect(f.work.tasks_late).toBe(0);
    }
  });

  it("shows the buttons by the server's rule and asks for days from the server's «today»", () => {
    const can = (granted: string[]) => (p: "tasks.assign" | "tasks.execute") => granted.includes(p);
    const toDirector = { audience: "director" } as AgentNote;
    const toHq = { audience: "hq" } as AgentNote;
    expect(mayAnswer(toHq, can(["tasks.assign"]))).toBe(true);
    expect(mayAnswer(toDirector, can(["tasks.execute"]))).toBe(true);
    expect(mayAnswer(toHq, can(["tasks.execute"]))).toBe(false);
    expect(mayAnswer(toDirector, can([]))).toBe(false); // the HQ analyst
    expect(askRange("2026-10-20")).toEqual({ min: "2026-10-20", max: "2026-11-03" });
    expect(askRange("2026-12-25").max).toBe("2027-01-08");
  });

  // Test engineer's pass after the stage 9 review (TC-UI-40). Runs last: the earlier answers stay in the tab.
  it("puts a note away with «Не нужно» for everyone in the HQ; a second answer is 409", () => {
    const check = note(ADMIN, "data_check");
    expect(post<AgentNote>(`/agents/notes/${check.id}/dismiss`, ADMIN).status).toBe("dismissed");
    expect(get<AgentNote[]>("/agents/notes", ADMIN).map((n) => n.id)).not.toContain(check.id);
    expect(get<AgentNote[]>("/agents/notes", ANALYST).map((n) => n.id)).not.toContain(check.id);
    expect(status(() => post(`/agents/notes/${check.id}/dismiss`, ADMIN))).toBe(409);
    expect(status(() => post(`/agents/notes/${check.id}/accept`, ADMIN))).toBe(409);
    expect(status(() => post("/agents/notes/no-such-note/dismiss", ADMIN))).toBe(404);
  });

  it("does not make a list for a chosen day without the server", () => {
    expect(status(() => post("/agents/inventory-prep", DIRECTOR))).toBe(404);
  });

  // Stage 10: the four notes to the HQ (TC-UI-42).
  it("shows the HQ the story, the letter, the transfer and the agenda; the director none of them", () => {
    const hq = get<AgentNote[]>("/agents/notes", ADMIN).map((n) => n.agent);
    for (const agent of ["shortage_story", "supplier_claim", "transfer", "hq_agenda"] as const)
      expect(hq).toContain(agent);
    expect(note(ADMIN, "hq_agenda").restaurant_name).toBeNull();
    expect(get<AgentNote[]>("/agents/notes", DIRECTOR).some((n) => n.audience === "hq")).toBe(false);
    const story = note(ADMIN, "shortage_story");
    expect(story.action).toBeNull();
    expect(status(() => post(`/agents/notes/${story.id}/accept`, ADMIN))).toBe(422);
  });

  it("sets both tasks of a transfer, as the server plans them; «Отправлено» makes no task", () => {
    const move = note(ADMIN, "transfer");
    expect(move.action_tasks.map((t) => t.title)).toHaveLength(2);
    expect(status(() => post(`/agents/notes/${move.id}/accept`, ANALYST))).toBe(403);
    const tasksBefore = get<ApiTask[]>("/tasks", ADMIN).length;
    const answer = post<AgentNote>(`/agents/notes/${move.id}/accept`, ADMIN);
    const tasks = get<ApiTask[]>("/tasks", ADMIN);
    expect(tasks.length).toBe(tasksBefore + 2);
    for (const planned of move.action_tasks) {
      const made = tasks.find((t) => t.title === planned.title)!;
      expect(made.restaurant_id).toBe(planned.restaurant_id);
      expect(made.checklist).toEqual(planned.checklist);
    }
    expect(answer.result_task_id).toBe(tasks.find((t) => t.title === move.action_tasks[0]!.title)!.id);

    const claim = note(ADMIN, "supplier_claim");
    const sent = post<AgentNote>(`/agents/notes/${claim.id}/accept`, ADMIN);
    expect([sent.status, sent.result_task_id]).toEqual(["accepted", null]);
    expect(get<ApiTask[]>("/tasks", ADMIN).length).toBe(tasksBefore + 2);
  });
});
