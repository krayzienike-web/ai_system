import { Link } from "@tanstack/react-router";
import { BellRing, ChevronDown, FlaskConical, Timer } from "lucide-react";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import { useCheckAction, useChecks, useTaskAction, useTasks } from "../../api/hooks";
import type { Check } from "../../api/types";
import { Button, Card, cx, EmptyState, ErrorText, PageTitle, Reveal, Skeleton } from "../../ds/primitives";
import { ddmm, money, plural, rub } from "../../lib/format";
import { useViewer } from "../../lib/useViewer";
import { useUi } from "../../state/ui";

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

export function DecisionsPage() {
  const checks = useChecks("proposed");
  const overdue = useTasks(true);
  const check = useCheckAction();
  const task = useTaskAction();
  const { notify } = useUi();
  const viewer = useViewer();
  if (checks.isError || overdue.isError) return <EmptyState title="Не получилось загрузить решения">Обновите страницу чуть позже.</EmptyState>;
  if (!checks.data || !overdue.data) return <Skeleton className="mx-auto h-96 max-w-[920px]" />;
  const proposed = checks.data;
  const late = overdue.data;
  const total = proposed.length + late.length;
  const decide = (id: string, d: "launch" | "reject") =>
    check.mutate(
      { id, action: d },
      { onSuccess: () => notify(d === "launch" ? "Проверка запущена, задачи отправлены директорам" : "Проверка отклонена") },
    );

  return (
    <div className="mx-auto max-w-[920px] space-y-8">
      <PageTitle title="Ждут вашего решения" subtitle={total ? "Все, что нельзя сделать без вас. Решения — прямо здесь." : undefined} />
      {!total && <EmptyState title="Все решения приняты">Новые вопросы появятся здесь — и на главной сети.</EmptyState>}

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
