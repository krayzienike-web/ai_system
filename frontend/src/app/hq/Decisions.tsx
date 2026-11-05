import { Link } from "@tanstack/react-router";
import { BellRing, ChevronDown, FlaskConical, ListTodo, Timer } from "lucide-react";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import { useAppContext, useAwaiting, useCheckAction, useChecks, useCreateTasks, useRestaurants, useTaskAction, useTasks } from "../../api/hooks";
import type { ApiFinding, Check } from "../../api/types";
import { Button, buttonClass, Card, cx, Dialog, EmptyState, ErrorText, PageTitle, Reveal, Skeleton } from "../../ds/primitives";
import { ddmm, money, plural, rub } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";
import { MoneyWords } from "../findings/parts";

const names = (places: Check["test"]) => places?.map((p) => p.name).join(", ") ?? "";
const weeks = (c: Check) => c.weeks;

function Section({ icon, title, count, children }: { icon: React.ReactNode; title: string; count: number; children: React.ReactNode }) {
  if (!count) return null;
  return (
    <Reveal>
      <section>
        <h2 className="mb-3 flex items-center gap-2 font-display text-lg font-semibold">
          {icon} {title} <span className="num rounded-full bg-spark px-2 text-sm text-ink">{count}</span>
        </h2>
        <div className="space-y-3">
          <AnimatePresence mode="popLayout">{children}</AnimatePresence>
        </div>
      </section>
    </Reveal>
  );
}

const exit = { opacity: 0, x: 60, transition: { duration: 0.3 } };

/** A proposed check as one scannable row; details (hypothesis, tasks) unfold on demand. */
function ProposedRow({ e, onDecide, canDecide, busy }: { e: Check; onDecide: (id: string, d: "launch" | "reject") => void; canDecide: boolean; busy: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <motion.li layout exit={{ opacity: 0, height: 0, transition: { duration: 0.25 } }} className="overflow-hidden">
      <div className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 px-4 py-4 sm:grid-cols-[1fr_auto_auto]">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="min-w-0 text-left">
          <span className="flex items-center gap-2 font-medium text-ink">
            <ChevronDown size={16} className={cx("shrink-0 text-ink-3 transition", open && "rotate-180")} />
            <span className="truncate">{e.title}</span>
          </span>
          <span className="mt-1 block truncate pl-6 text-sm text-ink-3">
            Пробуем: <span className="text-ink-2">{names(e.test)}</span> · сравниваем с: {e.control?.length ? names(e.control) : "внутри ресторана"} ·{" "}
            {plural(weeks(e), ["неделя", "недели", "недель"])}, до {ddmm(e.ends_on)}
          </span>
        </button>
        <span className="text-right">
          <span className="num block font-display text-lg font-semibold text-gain">+{rub(money(e.expected_rub_month) ?? 0)}</span>
          <span className="block text-[11px] text-ink-3">в месяц, если сработает</span>
        </span>
        {canDecide ? (
          <span className="col-span-2 flex gap-2 pl-6 sm:col-span-1 sm:pl-0">
            <Button size="sm" variant="primary" disabled={busy} onClick={() => onDecide(e.id, "launch")}>
              Запустить
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecide(e.id, "reject")}>
              Отклонить
            </Button>
          </span>
        ) : (
          <span className="col-span-2 pl-6 text-xs text-ink-3 sm:col-span-1 sm:pl-0">Запускает администратор УК</span>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="space-y-3 px-10 pb-5 text-sm">
              <p className="text-ink-2">{e.hypothesis}</p>
              <div className="rounded-[12px] bg-paper p-3 text-ink-2">
                <span className="font-medium text-ink">После запуска: </span>
                задача директору {(e.test ?? []).map((p) => `«${p.name}»`).join(" и ")} со сроком и чек-листом; замер — «{e.metric}».
              </div>
              <Link to="/checks/$checkId" params={{ checkId: e.id }} className="inline-block text-brand-strong hover:underline">
                Вся проверка →
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

/** The HQ's decision on a finding (ADR 0009): one task with the chosen steps as its checklist and a due date;
 * a network-wide finding goes to the restaurants chosen (all by default). */
function AssignDialog({ f, onClose }: { f: ApiFinding; onClose: () => void }) {
  const create = useCreateTasks();
  const context = useAppContext();
  const restaurants = useRestaurants();
  const { notify } = useUi();
  const [steps, setSteps] = useState<boolean[]>(() => f.actions.map((_, i) => i === 0));
  const [due, setDue] = useState(1);
  const [places, setPlaces] = useState<string[] | null>(null); // null: every restaurant
  const options = context.data?.due_options ?? [];
  const option = options[due];
  const chosen = f.actions.filter((_, i) => steps[i]);
  const all = (restaurants.data ?? []).map((r) => r.id);
  const targets = f.restaurant_id ? undefined : (places ?? all);
  return (
    <Dialog open onClose={onClose} title="Поставить задачу">
      <div className="space-y-5 text-sm">
        <p className="text-ink-2">
          «{f.title}» — {f.restaurant_name ? `директору: ${f.restaurant_name}` : "директорам выбранных ресторанов"}.
        </p>
        <fieldset>
          <legend className="mb-2 font-medium text-ink">Что сделать</legend>
          <div className="space-y-2">
            {f.actions.map((a, i) => (
              <label key={a} className="flex cursor-pointer items-start gap-2.5 rounded-[10px] border border-line p-3 hover:border-brand">
                <input
                  type="checkbox"
                  checked={steps[i] ?? false}
                  onChange={() => setSteps((s) => s.map((v, j) => (j === i ? !v : v)))}
                  className="mt-0.5 h-4 w-4 accent-[#0a8f84]"
                />
                <span>{a}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {!f.restaurant_id && (
          <fieldset>
            <legend className="mb-2 font-medium text-ink">Рестораны</legend>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {(restaurants.data ?? []).map((r) => {
                const on = (places ?? all).includes(r.id);
                return (
                  <label key={r.id} className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => setPlaces((p) => ((p ?? all).includes(r.id) ? (p ?? all).filter((x) => x !== r.id) : [...(p ?? all), r.id]))}
                      className="h-4 w-4 accent-[#0a8f84]"
                    />
                    {r.code} · {r.name}
                  </label>
                );
              })}
            </div>
          </fieldset>
        )}
        <fieldset>
          <legend className="mb-2 font-medium text-ink">Срок</legend>
          <div className="flex flex-wrap gap-2">
            {options.map((d, i) => (
              <button
                key={d.days}
                type="button"
                onClick={() => setDue(i)}
                aria-pressed={due === i}
                className={cx(
                  "rounded-full border px-3 py-1.5",
                  due === i ? "border-brand bg-brand-soft font-medium text-brand-strong" : "border-line-strong text-ink-2",
                )}
              >
                {d.label} <span className="text-ink-3">· до {ddmm(d.due_on)}</span>
              </button>
            ))}
          </div>
        </fieldset>
        <ErrorText error={create.error} fallback="Не получилось поставить задачу. Попробуйте еще раз." />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            disabled={!chosen.length || !option || (targets !== undefined && !targets.length) || create.isPending}
            onClick={() =>
              create.mutate(
                {
                  title: chosen[0]!,
                  checklist: chosen.length > 1 ? chosen : [],
                  finding_id: f.id,
                  due_on: option!.due_on,
                  restaurant_ids: targets,
                },
                {
                  onSuccess: () => {
                    notify(f.restaurant_id ? "Задача поставлена директору" : `Задача поставлена директорам: ${targets!.length}`);
                    onClose();
                  },
                },
              )
            }
          >
            Поставить задачу
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** A reviewed finding nobody acted on: the HQ sets a task on the director or checks the change first. */
function AwaitingRow({ f, canAssign }: { f: ApiFinding; canAssign: boolean }) {
  const [assigning, setAssigning] = useState(false);
  return (
    <motion.li layout exit={{ opacity: 0, height: 0, transition: { duration: 0.25 } }} className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4">
        <div className="min-w-0 flex-1">
          <Link to="/findings/$findingId" params={{ findingId: f.id }} className="block font-semibold hover:underline">
            {f.title}
          </Link>
          <span className="mt-0.5 block text-sm text-ink-3">
            {f.restaurant_name ?? "Вся сеть"} · <MoneyWords f={f} />
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canAssign ? (
            <Button variant="primary" onClick={() => setAssigning(true)}>
              Поставить задачу
            </Button>
          ) : (
            <span className="text-xs text-ink-3">Задачу ставит администратор УК</span>
          )}
          {f.restaurant_id && (
            <Link to="/checks/new/$findingId" params={{ findingId: f.id }} className={buttonClass("ghost")}>
              <FlaskConical size={15} /> Сначала проверить
            </Link>
          )}
        </div>
      </div>
      {assigning && <AssignDialog f={f} onClose={() => setAssigning(false)} />}
    </motion.li>
  );
}

export function DecisionsPage() {
  const checks = useChecks("proposed");
  const overdue = useTasks(true);
  const awaiting = useAwaiting();
  const check = useCheckAction();
  const task = useTaskAction();
  const { notify } = useUi();
  const viewer = useViewer();
  if (checks.isError || overdue.isError || awaiting.isError) return <EmptyState title="Не получилось загрузить решения">Обновите страницу чуть позже.</EmptyState>;
  if (!checks.data || !overdue.data || !awaiting.data) return <Skeleton className="mx-auto h-96 max-w-[920px]" />;
  const proposed = checks.data;
  const late = overdue.data;
  const found = awaiting.data;
  const total = proposed.length + late.length + found.length;
  const decide = (id: string, d: "launch" | "reject") =>
    check.mutate(
      { id, action: d },
      { onSuccess: () => notify(d === "launch" ? "Проверка запущена, задачи отправлены директорам" : "Проверка отклонена") },
    );

  return (
    <div className="mx-auto max-w-[920px] space-y-8">
      <PageTitle title="Ждут вашего решения" subtitle={total ? "Все, что нельзя сделать без вас. Решения — прямо здесь." : undefined} />
      {!total && <EmptyState title="Все решения приняты">Новые вопросы появятся здесь — и на главной сети.</EmptyState>}

      <Section icon={<ListTodo size={20} />} title="Решить по находке" count={found.length}>
        <motion.div key="awaiting" layout exit={exit}>
          <p className="mb-2 text-sm text-ink-3">
            Находки прошли проверку. Директор увидит находку, когда управляющая компания поставит по ней задачу.
          </p>
          <Card className="p-2">
            <ul className="divide-y divide-line">
              <AnimatePresence initial={false}>
                {found.map((f) => (
                  <AwaitingRow key={f.id} f={f} canAssign={!!viewer?.can("tasks.assign")} />
                ))}
              </AnimatePresence>
            </ul>
          </Card>
        </motion.div>
      </Section>

      <Section icon={<FlaskConical size={20} />} title="Проверки к запуску" count={proposed.length}>
        <motion.div key="proposed" layout exit={exit}>
          <Card className="p-2">
            <ul className="divide-y divide-line">
              <AnimatePresence initial={false}>
                {proposed.map((e) => (
                  <ProposedRow key={e.id} e={e} onDecide={decide} canDecide={!!viewer?.can("experiments.launch")} busy={check.isPending} />
                ))}
              </AnimatePresence>
            </ul>
            <ErrorText error={check.error} className="px-4 pb-3" />
          </Card>
        </motion.div>
      </Section>

      <Section icon={<Timer size={20} />} title="Просроченные задачи" count={late.length}>
        {late.map((t) => (
          <motion.div key={t.id} layout exit={exit}>
            <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
              <div>
                <div className="font-semibold">{t.title}</div>
                <div className="text-sm text-ink-3">
                  {t.restaurant_name} · срок был {ddmm(t.due_on)}
                  {t.reminded_on && ` · напомнили ${ddmm(t.reminded_on)}`}
                </div>
              </div>
              {viewer?.can("tasks.assign") && (
                <Button
                  disabled={task.isPending}
                  onClick={() => task.mutate({ id: t.id, action: "remind" }, { onSuccess: () => notify("Директору отправлено напоминание") })}
                >
                  <BellRing size={15} /> Напомнить
                </Button>
              )}
            </Card>
          </motion.div>
        ))}
        <ErrorText error={task.error} />
      </Section>
    </div>
  );
}
