import { CheckCircle2, FileSpreadsheet, UploadCloud } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { Button, Card, cx, EASE, PageTitle, Pill, QuestionBlock, Reveal } from "../ds/primitives";
import { useViewer } from "../lib/useViewer";
import { FRESHNESS, PERIOD, RESTAURANTS } from "../mock/data";

const SOURCES = [
  { key: "r_keeper", system: "r_keeper", what: "Продажи блюд" },
  { key: "iiko", system: "iiko", what: "Склад, техкарты, инвентаризации" },
  { key: "erp", system: "1С:ERP", what: "Закупки и цены" },
] as const;

type Step = "drop" | "understood" | "checked" | "done";

/** Upload in plain language: we recognise the file, show how we understood it, check it, load it. */
function Upload({ restaurant }: { restaurant: string }) {
  const [step, setStep] = useState<Step>("drop");
  return (
    <Card className="overflow-hidden">
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: EASE }}
          className="p-6"
        >
          {step === "drop" && (
            <button
              type="button"
              onClick={() => setStep("understood")}
              className="flex w-full flex-col items-center gap-3 rounded-[16px] border-2 border-dashed border-line-strong bg-paper px-6 py-10 text-center transition hover:border-brand"
            >
              <UploadCloud size={32} className="text-brand" />
              <span className="font-display text-lg font-semibold">Перетащите выгрузку сюда</span>
              <span className="max-w-md text-sm text-ink-2">
                Excel или CSV из r_keeper, iiko или 1С. Приводить файл к шаблону не нужно — мы сами поймем, что в нем.
              </span>
              <span className="text-xs text-ink-3">В прототипе загрузится пример: инвентаризация из iiko</span>
            </button>
          )}
          {step !== "drop" && (
            <div className="space-y-5">
              <div className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-[12px] bg-brand-soft text-brand-strong">
                  <FileSpreadsheet size={22} />
                </span>
                <div>
                  <div className="font-medium">inventarizaciya_01-10.xlsx</div>
                  <div className="text-sm text-ink-3">412 строк</div>
                </div>
              </div>
              <div className="rounded-[14px] bg-paper p-4">
                <div className="font-medium">Мы поняли файл так:</div>
                <div className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
                  <div>
                    <div className="text-ink-3">Что это</div>
                    <div className="font-medium">Инвентаризация из iiko</div>
                  </div>
                  <div>
                    <div className="text-ink-3">Ресторан</div>
                    <div className="font-medium">{restaurant}</div>
                  </div>
                  <div>
                    <div className="text-ink-3">Дата</div>
                    <div className="font-medium">01.10.2026</div>
                  </div>
                </div>
                <div className="mt-3 text-sm text-ink-2">
                  Колонка «Номенклатура» — это товар, «Фактический остаток» — сколько насчитали. Если что-то не так, поправьте.
                </div>
              </div>
              {step === "understood" && (
                <div className="flex gap-2">
                  <Button variant="primary" onClick={() => setStep("checked")}>
                    Да, все верно — проверить
                  </Button>
                  <Button variant="ghost" onClick={() => setStep("drop")}>
                    Другой файл
                  </Button>
                </div>
              )}
              {step !== "understood" && (
                <ul className="space-y-2 text-sm">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 size={16} className="text-gain" /> 408 строк в порядке
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 grid h-4 w-4 place-items-center rounded-full bg-warn-soft text-[10px] font-bold text-warn">!</span>
                    <span>
                      4 товара назывались иначе. Например, «Моцарелла фиор ди латте» — это «Сыр Моцарелла 45%»?{" "}
                      <span className="text-ink-3">Запомним ответ и больше не спросим.</span>
                    </span>
                  </li>
                </ul>
              )}
              {step === "checked" && (
                <Button variant="primary" onClick={() => setStep("done")}>
                  Загрузить
                </Button>
              )}
              {step === "done" && (
                <motion.div
                  initial={{ scale: 0.95, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  className="flex flex-wrap items-center gap-3 rounded-[14px] bg-gain-soft p-4 text-sm text-gain"
                >
                  <CheckCircle2 size={18} /> Загружено. Пересчитываем — неделя обновится через пару минут.
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setStep("drop")}>
                    Загрузить еще
                  </Button>
                </motion.div>
              )}
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </Card>
  );
}

export function DataPage() {
  const viewer = useViewer();
  if (!viewer) return null;
  const restaurants = RESTAURANTS.filter((r) => viewer.isHq || r.code === viewer.restaurantCode);
  const stale = FRESHNESS.filter((f) => restaurants.some((r) => r.code === f.restaurantId) && f.status !== "good");

  return (
    <div className="mx-auto max-w-[1040px] space-y-6">
      <PageTitle title="Данные" subtitle="Откуда система берет цифры и насколько они свежие" />
      <Reveal>
        <Upload restaurant={restaurants[0]?.name ?? ""} />
      </Reveal>
      <Reveal index={1}>
        <QuestionBlock
          question="Все ли данные на месте?"
          answer={
            stale.length
              ? `Почти: ${stale.map((s) => `${RESTAURANTS.find((r) => r.code === s.restaurantId)?.name} — ${s.dataset.toLowerCase()} только по ${s.lastDate}`).join("; ")}.`
              : `Да, все данные загружены по ${PERIOD.dataUntil.slice(0, 5)}.`
          }
        >
          <div className="space-y-4">
            {restaurants.map((r) => (
              <div key={r.code}>
                <div className="mb-2 font-medium">{r.name}</div>
                <div className="grid gap-2 sm:grid-cols-3">
                  {SOURCES.map((s) => {
                    const f = FRESHNESS.find((x) => x.restaurantId === r.code && x.source === s.key)!;
                    return (
                      <div
                        key={s.key}
                        className={cx("rounded-[12px] border p-3", f.status === "good" ? "border-line" : "border-warn-icon/50 bg-warn-soft/40")}
                      >
                        <div className="text-xs text-ink-3">{s.system}</div>
                        <div className="text-sm font-medium">{s.what}</div>
                        <div className="mt-2">
                          <Pill tone={f.status === "good" ? "gain" : "warn"}>по {f.lastDate}</Pill>
                        </div>
                        {f.note && <div className="mt-1 text-xs text-ink-3">{f.note}</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </QuestionBlock>
      </Reveal>
    </div>
  );
}
