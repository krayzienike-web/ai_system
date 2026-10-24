import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

import { Logo, LogoMark } from "../brand/Logo";
import { AiBadge, ConfidenceNote, VerifiedNote } from "../ds/ai";
import { Button, Card, Pill, QuestionBlock, Term } from "../ds/primitives";
import { AreaTrend, BulletScale, CompositionBar, CycleSteps, ProcessMap, RankList } from "../ds/viz";
import { pct, rub } from "../lib/format";

const COLORS: [string, string, string][] = [
  ["Графит", "#14202B", "текст, темные панели"],
  ["Базилик", "#0A8F84", "главные действия, «мой ресторан»"],
  ["Шафран", "#F2B33D", "только ИИ и знак"],
  ["Бумага", "#F2F5F4", "фон"],
  ["Сеть", "#EB6834", "среднее по сети на графиках"],
  ["Теряем", "#B42318", "потери, проблемы"],
  ["Можно заработать", "#1F7A3A", "возможности, норма"],
  ["Внимание", "#8A5A00", "пробелы, предупреждения"],
];

const VOICE: [string, string][] = [
  ["Теряем 38 тыс ₽ в месяц", "−38 тыс ₽/мес"],
  ["Моцареллы уходит на 9% больше нормы", "Расход сверх ТТК: 9,1%"],
  ["Где пробуем / С чем сравниваем", "Тестовая / контрольная группа"],
  ["Скорее всего от 3 до 7 тыс ₽ в месяц", "Интервал 3,1–7,3 тыс"],
  ["Уверены средне — одна инвентаризация", "Уверенность: средняя"],
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-xl font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** Living style guide: the brand and components exactly as the product renders them. */
export function DesignSystemPage() {
  return (
    <div className="min-h-screen bg-paper">
      <div className="mx-auto max-w-[1100px] space-y-12 px-4 py-10 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link to="/login" className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
            <ArrowLeft size={14} /> Вход
          </Link>
          <span className="text-sm text-ink-3">docs/ux/02-brand-design-system.md</span>
        </div>
        <header className="rounded-[24px] bg-ink p-8 text-white sm:p-12">
          <div className="flex items-center gap-3">
            <LogoMark size={48} inverted />
            <span className="font-display text-4xl font-semibold">SousChef</span>
            <span className="rounded-md border border-white/30 px-1.5 py-0.5 text-xs font-semibold">AI</span>
          </div>
          <p className="mt-6 max-w-xl text-lg text-white/80">
            Су-шеф управляющего: готовит анализ, находит потери и подсказывает следующий шаг. Решает человек.
          </p>
          <div className="mt-6 flex flex-wrap gap-2 text-sm">
            {["Деньги, а не графики", "Ясность", "Честность", "Партнерство", "Действие"].map((v) => (
              <span key={v} className="rounded-full bg-white/10 px-3 py-1">
                {v}
              </span>
            ))}
          </div>
        </header>

        <Section title="Логотип">
          <div className="grid gap-4 sm:grid-cols-3">
            <Card className="grid place-items-center p-8">
              <Logo />
            </Card>
            <div className="grid place-items-center rounded-[16px] bg-ink p-8">
              <span className="inline-flex items-center gap-2.5 text-white">
                <LogoMark inverted />
                <span className="font-display text-[17px] font-semibold">SousChef</span>
              </span>
            </div>
            <Card className="flex items-center justify-center gap-4 p-8">
              <LogoMark size={20} />
              <LogoMark size={32} />
              <LogoMark size={56} />
            </Card>
          </div>
          <p className="text-sm text-ink-3">Колпак шефа — отрасль; искра шафранового цвета — помощник, который подсказывает.</p>
        </Section>

        <Section title="Цвет">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {COLORS.map(([name, hex, role]) => (
              <Card key={hex} className="overflow-hidden">
                <div className="h-20" style={{ background: hex }} />
                <div className="p-3">
                  <div className="font-medium">{name}</div>
                  <div className="num text-xs text-ink-3">{hex}</div>
                  <div className="mt-1 text-xs text-ink-2">{role}</div>
                </div>
              </Card>
            ))}
          </div>
        </Section>

        <Section title="Типографика">
          <Card className="space-y-4 p-6">
            <div className="font-display text-5xl font-semibold tracking-tight">128 тыс ₽</div>
            <div className="font-display text-2xl font-semibold">Unbounded — заголовки и главные суммы</div>
            <p className="max-w-[65ch] text-[15px] leading-relaxed text-ink-2">
              Onest — весь интерфейс и текст. Шрифт создан для русского интерфейса: спокойный, хорошо читается в мелком размере, а цифры в таблицах
              стоят ровным столбцом: <span className="num">1 012 · 920 · 84</span>.
            </p>
          </Card>
        </Section>

        <Section title="Голос">
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-ink-3">
                <tr>
                  <th className="px-5 py-3 font-medium">Пишем так</th>
                  <th className="px-5 py-3 font-medium">Не так</th>
                </tr>
              </thead>
              <tbody>
                {VOICE.map(([yes, no]) => (
                  <tr key={yes} className="border-t border-line">
                    <td className="px-5 py-3 font-medium text-gain">{yes}</td>
                    <td className="px-5 py-3 text-ink-3 line-through">{no}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </Section>

        <Section title="Анатомия блока">
          <QuestionBlock
            question="Вопрос пользователя"
            answer="Ответ одной фразой — вывод и сумма."
            action={<Button variant="primary">Одно действие</Button>}
            source={<VerifiedNote>период и источник</VerifiedNote>}
          >
            <div className="grid h-24 place-items-center rounded-[12px] border border-dashed border-line-strong text-sm text-ink-3">
              Визуализация, где хорошо и плохо видно без легенды
            </div>
          </QuestionBlock>
        </Section>

        <Section title="Элементы">
          <Card className="space-y-6 p-6">
            <div className="flex flex-wrap gap-2">
              <Button variant="primary">Взять в работу</Button>
              <Button>Поставить задачу</Button>
              <Button variant="ghost">Подробнее</Button>
              <Button variant="danger">Отклонить</Button>
            </div>
            <div className="flex flex-wrap gap-2">
              <Pill tone="loss">Проблема</Pill>
              <Pill tone="gain">Сработало</Pill>
              <Pill tone="warn">Просрочено</Pill>
              <Pill tone="info">Делаем</Pill>
              <Pill>Нашли</Pill>
            </div>
            <div className="flex flex-wrap items-center gap-6 text-sm">
              <span className="inline-flex items-center gap-2">
                Текст от ИИ <AiBadge basis="Пример: на чем основан вывод, период и источники." />
              </span>
              <ConfidenceNote confidence="medium" reason="Одна полная инвентаризация" />
              <span>
                Термин с подсказкой: <Term hint="Сколько продукта должно уйти по техкартам проданных блюд">расход по норме</Term>
              </span>
            </div>
          </Card>
        </Section>

        <Section title="Визуализация">
          <div className="grid gap-4 md:grid-cols-2">
            <Card className="p-6">
              <div className="text-sm font-medium">Шкала «я / сеть / норма»</div>
              <BulletScale me={9.1} network={3.4} norm={2} format={(n) => pct(n)} />
            </Card>
            <Card className="p-6">
              <div className="mb-4 text-sm font-medium">Из чего сложилось</div>
              <CompositionBar
                format={(n) => `${n} кг`}
                parts={[
                  { label: "по техкартам", value: 920, tone: "brand" },
                  { label: "списано", value: 3, tone: "neutral" },
                  { label: "не объяснено", value: 84, tone: "loss" },
                ]}
              />
            </Card>
            <Card className="p-6">
              <div className="mb-2 text-sm font-medium">Рейтинг</div>
              <RankList
                items={[
                  { id: "a", title: "Ресторан на Тверской", value: 78000, valueLabel: rub(78000), delta: -8000 },
                  { id: "b", title: "Ресторан на Арбате", value: 45000, valueLabel: rub(45000), delta: 4000 },
                  { id: "c", title: "Ресторан на Невском", value: 34000, valueLabel: rub(34000), delta: 0 },
                ]}
              />
            </Card>
            <Card className="p-6">
              <div className="mb-2 text-sm font-medium">Тренд</div>
              <AreaTrend
                labels={["1", "2", "3", "4", "5", "6"]}
                series={[{ name: "Потенциал прибыли", values: [331, 318, 309, 301, 290, 274], color: "#0a8f84", fill: true }]}
                format={(n) => `${n} тыс`}
              />
            </Card>
            <Card className="p-6 md:col-span-2">
              <div className="mb-4 text-sm font-medium">Цикл и процессы</div>
              <div className="max-w-xl">
                <CycleSteps current={2} notes={[undefined, undefined, "до 10.11"]} />
              </div>
              <div className="mt-6">
                <ProcessMap
                  tiles={[
                    { key: "purchasing", title: "Закупка", status: "warning", losses: 21000, detail: "21 тыс ₽ в месяц" },
                    { key: "receiving", title: "Приемка", status: "good", losses: 0, detail: "" },
                    { key: "production", title: "Производство (ТТК)", status: "critical", losses: 38000, detail: "38 тыс ₽ в месяц" },
                    { key: "accounting", title: "Учет и данные", status: "warning", losses: 0, detail: "" },
                  ]}
                />
              </div>
            </Card>
          </div>
        </Section>
      </div>
    </div>
  );
}
