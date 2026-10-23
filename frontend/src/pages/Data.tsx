import { CheckCircle2, FileSpreadsheet, Upload } from "lucide-react";
import { useState } from "react";

import { Button, Card, PageHeader, SectionTitle, StatusChip } from "../components/ui";
import { useViewer } from "../lib/useViewer";
import { FRESHNESS, RESTAURANTS } from "../mock/data";

const SOURCE_LABEL = { r_keeper: "r_keeper", iiko: "iiko", erp: "1С:ERP" } as const;

type Step = "idle" | "mapping" | "checked" | "done";

// Simulated upload of an iiko inventory export: detection → column mapping → validation → publish.
function UploadWizard({ restaurantName }: { restaurantName: string }) {
  const [step, setStep] = useState<Step>("idle");

  if (step === "idle") {
    return (
      <button
        type="button"
        onClick={() => setStep("mapping")}
        className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-300 bg-white p-8 text-slate-600 hover:border-slate-400"
      >
        <Upload size={24} />
        <span className="font-medium text-slate-800">Перетащите файл XLS/CSV или нажмите, чтобы выбрать</span>
        <span className="text-sm">Выгрузки r_keeper, iiko, 1С:ERP — формат определится автоматически</span>
        <span className="text-xs text-slate-400">В прототипе загрузится пример: инвентаризация iiko</span>
      </button>
    );
  }

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <FileSpreadsheet size={18} />
        <div>
          <div className="font-medium">inventarizaciya_01-10.xlsx</div>
          <div className="text-xs text-slate-500">
            Распознано: iiko · Инвентаризация · {restaurantName} · 01.10.2026 · 412 строк
          </div>
        </div>
      </div>

      <SectionTitle aside="профиль сохранится для следующих загрузок">Сопоставление колонок</SectionTitle>
      <table className="mb-4 w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr>
            <th className="py-1 font-normal">Колонка в файле</th>
            <th className="py-1 font-normal">Поле системы</th>
            <th className="py-1 font-normal">Пример</th>
          </tr>
        </thead>
        <tbody>
          {[
            ["Номенклатура", "Товар", "Сыр Моцарелла 45%"],
            ["Ед. изм.", "Единица", "кг"],
            ["Учетный остаток", "Остаток по учету", "47,200"],
            ["Фактический остаток", "Остаток факт", "43,000"],
            ["Сумма расхождения", "Сумма расхождения, ₽", "−3 801,00"],
          ].map(([from, to, sample]) => (
            <tr key={from} className="border-t border-slate-100">
              <td className="py-1.5">{from}</td>
              <td className="py-1.5 font-medium">{to}</td>
              <td className="py-1.5 text-slate-500">{sample}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {step === "mapping" && (
        <Button variant="primary" onClick={() => setStep("checked")}>
          Проверить данные
        </Button>
      )}
      {step !== "mapping" && (
        <div className="mb-4 space-y-1 text-sm">
          <StatusChip status="good" label="408 строк без ошибок" />
          <div>
            <StatusChip status="warning" label="4 товара не сопоставлены с номенклатурой сети — предложены варианты" />
          </div>
          <div className="pl-5 text-xs text-slate-500">«Моцарелла фиор ди латте» → «Сыр Моцарелла 45%»? (совпадение 86%)</div>
        </div>
      )}
      {step === "checked" && (
        <Button variant="primary" onClick={() => setStep("done")}>
          Подтвердить и загрузить
        </Button>
      )}
      {step === "done" && (
        <div className="flex items-center gap-2 rounded-md bg-emerald-50 p-3 text-sm text-emerald-900">
          <CheckCircle2 size={16} /> Загружено. Пересчет аналитики запущен — сводка обновится через пару минут.
          <Button variant="ghost" onClick={() => setStep("idle")}>
            Загрузить еще
          </Button>
        </div>
      )}
    </Card>
  );
}

export function DataPage() {
  const viewer = useViewer();
  if (!viewer) return null;
  const restaurants = RESTAURANTS.filter((r) => viewer.isHq || r.code === viewer.restaurantCode);
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Данные" meta="Загрузка выгрузок и свежесть данных по источникам" />
      <section className="mb-8">
        <UploadWizard restaurantName={restaurants[0]?.name ?? ""} />
      </section>
      <section>
        <SectionTitle>Свежесть данных</SectionTitle>
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2 font-normal">Ресторан</th>
                {(["r_keeper", "iiko", "erp"] as const).map((s) => (
                  <th key={s} className="px-3 py-2 font-normal">
                    {SOURCE_LABEL[s]} · {FRESHNESS.find((f) => f.source === s)?.dataset.toLowerCase()}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {restaurants.map((r) => (
                <tr key={r.code} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{r.name}</td>
                  {(["r_keeper", "iiko", "erp"] as const).map((s) => {
                    const f = FRESHNESS.find((x) => x.restaurantId === r.code && x.source === s)!;
                    return (
                      <td key={s} className="px-3 py-2">
                        <StatusChip status={f.status} label={`по ${f.lastDate}`} />
                        {f.note && <div className="text-xs text-slate-500">{f.note}</div>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  );
}
