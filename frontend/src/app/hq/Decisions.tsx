import { Link } from "@tanstack/react-router";
import { BellRing, FlaskConical, MessageSquareWarning, Timer } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { Button, Card, EmptyState, PageTitle, Reveal } from "../../ds/primitives";
import { perMonth } from "../../lib/format";
import { RESTAURANTS } from "../../mock/data";
import { findingById, restaurantByCode } from "../../mock/selectors";
import { usePrototype } from "../../state/prototype";
import { useInbox } from "../counts";

const names = (codes: string[]) => codes.map((c) => restaurantByCode(c)?.name ?? c).join(", ");

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

export function DecisionsPage() {
  const { experiments, disputed, overdue, drafts } = useInbox();
  const { decideExperiment, resolveDispute, notify } = usePrototype();
  const total = experiments.length + disputed.length + overdue.length + drafts.length;

  return (
    <div className="mx-auto max-w-[920px] space-y-8">
      <PageTitle
        title="Ждут вашего решения"
        subtitle={total ? "Все, что нельзя сделать без вас. Решения — прямо здесь." : undefined}
      />
      {!total && <EmptyState title="Все решения приняты">Новые вопросы появятся здесь — и на главной сети.</EmptyState>}

      <Section icon={<FlaskConical size={20} />} title="Проверки на утверждение" count={experiments.length}>
        {experiments.map((e) => (
          <motion.div key={e.id} layout exit={exit}>
            <Card className="p-5">
              <div className="font-semibold">{e.title}</div>
              <p className="mt-1 text-sm text-ink-2">{e.hypothesis}</p>
              <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
                <div className="rounded-[12px] bg-brand-soft p-3">
                  <div className="text-xs text-brand-strong">Где пробуем</div>
                  <div className="font-medium">{names(e.test)}</div>
                </div>
                <div className="rounded-[12px] bg-paper p-3">
                  <div className="text-xs text-ink-3">С чем сравниваем</div>
                  <div className="font-medium">{e.control.length ? names(e.control) : "внутри ресторана"}</div>
                </div>
                <div className="rounded-[12px] bg-paper p-3">
                  <div className="text-xs text-ink-3">Если сработает</div>
                  <div className="font-medium text-gain">+{perMonth(e.expectedRubMonth)}</div>
                </div>
              </div>
              <div className="mt-4 rounded-[12px] border border-dashed border-line-strong p-3 text-sm text-ink-2">
                <span className="font-medium text-ink">Задачи после утверждения: </span>
                {e.test.map((c) => `директору «${restaurantByCode(c)?.name}» — ${e.title.toLowerCase()}`).join("; ")}. Срок — {e.period}.
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => decideExperiment(e.id, "approved")}>
                  Утвердить и поставить задачи
                </Button>
                <Link to="/checks/$checkId" params={{ checkId: e.id }} className="inline-flex h-10 items-center px-3 text-sm font-medium text-ink-2 hover:text-ink">
                  Подробнее
                </Link>
                <Button variant="ghost" className="ml-auto" onClick={() => decideExperiment(e.id, "rejected")}>
                  Отклонить
                </Button>
              </div>
            </Card>
          </motion.div>
        ))}
      </Section>

      <Section icon={<FlaskConical size={20} />} title="Черновики проверок от команды" count={drafts.length}>
        {drafts.map((id) => {
          const f = findingById(id);
          return (
            <motion.div key={id} layout exit={exit}>
              <Card className="p-5 text-sm">
                <div className="font-semibold">{f?.actions[0]}</div>
                <div className="mt-1 text-ink-3">По находке «{f?.title}» · отправлено на утверждение</div>
              </Card>
            </motion.div>
          );
        })}
      </Section>

      <Section icon={<MessageSquareWarning size={20} />} title="Директора не согласны" count={disputed.length}>
        {disputed.map(({ finding, dispute }) => (
          <motion.div key={finding.id} layout exit={exit}>
            <Card className="p-5">
              <Link to="/findings/$findingId" params={{ findingId: finding.id }} className="font-semibold hover:underline">
                {finding.title}
              </Link>
              <div className="mt-1 text-sm text-ink-3">
                {restaurantByCode(finding.restaurantId ?? "")?.name} · {finding.effectRubMonth !== null && perMonth(finding.effectRubMonth)}
              </div>
              <blockquote className="mt-3 rounded-[12px] bg-warn-soft p-3 text-sm">
                <div className="font-medium">
                  {dispute.by}: «{dispute.reason}»
                </div>
                {dispute.comment && <div className="mt-1 text-ink-2">{dispute.comment}</div>}
              </blockquote>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => resolveDispute(finding.id)}>
                  Директор прав — закрыть находку
                </Button>
                <Button onClick={() => resolveDispute(finding.id)}>Проверим данные — оставить</Button>
              </div>
            </Card>
          </motion.div>
        ))}
      </Section>

      <Section icon={<Timer size={20} />} title="Просроченные задачи" count={overdue.length}>
        {overdue.map((t) => (
          <motion.div key={t.id} layout exit={exit}>
            <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
              <div>
                <div className="font-semibold">{t.title}</div>
                <div className="text-sm text-ink-3">
                  {RESTAURANTS.find((r) => r.code === t.restaurantId)?.name} · срок был {t.due}
                </div>
              </div>
              <Button onClick={() => notify("Директору отправлено напоминание")}>
                <BellRing size={15} /> Напомнить
              </Button>
            </Card>
          </motion.div>
        ))}
      </Section>
    </div>
  );
}
