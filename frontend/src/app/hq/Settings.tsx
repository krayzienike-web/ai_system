import { useState } from "react";

import { Button, PageTitle, QuestionBlock, Reveal } from "../../ds/primitives";
import { usePrototype } from "../../state/prototype";

const CATEGORIES: { name: string; value: number; example: string }[] = [
  { name: "Овощи и зелень", value: 3, example: "очистка, обрезка" },
  { name: "Мясо и птица", value: 2, example: "зачистка, ужарка" },
  { name: "Рыба", value: 2, example: "разделка" },
  { name: "Молочные продукты и сыры", value: 2, example: "порционирование" },
  { name: "Напитки", value: 1, example: "розлив" },
];

export function SettingsPage() {
  const { notify } = usePrototype();
  const [tolerances, setTolerances] = useState(CATEGORIES.map((c) => c.value));
  const [target, setTarget] = useState(30);
  return (
    <div className="mx-auto max-w-[760px] space-y-6">
      <PageTitle title="Нормы и настройки" subtitle="По этим нормам су-шеф решает, что считать проблемой" />
      <Reveal>
        <QuestionBlock
          question="Сколько продукта можно терять сверх техкарты?"
          answer="Если расход выше нормы на эту величину, су-шеф покажет проблему. Сейчас стоят отраслевые значения."
        >
          <div className="space-y-5">
            {CATEGORIES.map((c, i) => (
              <div key={c.name}>
                <div className="flex items-baseline justify-between">
                  <label htmlFor={`tol-${i}`} className="font-medium">
                    {c.name}
                  </label>
                  <span className="num font-display text-lg font-semibold">{tolerances[i]}%</span>
                </div>
                <input
                  id={`tol-${i}`}
                  type="range"
                  min={0}
                  max={8}
                  step={0.5}
                  value={tolerances[i]}
                  onChange={(e) => setTolerances((t) => t.map((v, j) => (j === i ? Number(e.target.value) : v)))}
                  className="mt-2 w-full accent-[#0a8f84]"
                />
                <div className="text-xs text-ink-3">Учитывает {c.example}</div>
              </div>
            ))}
          </div>
        </QuestionBlock>
      </Reveal>
      <Reveal index={1}>
        <QuestionBlock
          question="Какой фудкост вы считаете нормальным?"
          answer="Блюда с фудкостом выше этой цифры су-шеф предложит пересмотреть по цене или техкарте."
        >
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={20}
              max={40}
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
              className="flex-1 accent-[#0a8f84]"
              aria-label="Целевой фудкост"
            />
            <span className="num font-display text-2xl font-semibold">{target}%</span>
          </div>
        </QuestionBlock>
      </Reveal>
      <Button variant="primary" onClick={() => notify("Нормы сохранены. Находки пересчитаются за пару минут")}>
        Сохранить нормы
      </Button>
    </div>
  );
}
