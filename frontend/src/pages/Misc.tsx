import { ChatPanel } from "../components/Chat";
import { DigestView } from "../components/DigestView";
import { Card, PageHeader, SectionTitle } from "../components/ui";
import { useViewer } from "../lib/useViewer";
import { NetworkPage } from "./Network";

export function HomePage() {
  const viewer = useViewer();
  if (!viewer) return null;
  if (viewer.isHq) return <NetworkPage />;
  return viewer.restaurantCode ? <DigestView code={viewer.restaurantCode} isDirector /> : null;
}

export function AssistantPage() {
  const viewer = useViewer();
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Ассистент"
        meta={viewer?.isHq ? "Вопросы по данным всей сети" : "Вопросы по данным вашего ресторана и среднему по сети"}
      />
      <Card className="flex h-[70vh] flex-col overflow-hidden">
        <ChatPanel context={null} className="flex-1" />
      </Card>
    </div>
  );
}

const TOLERANCES: [string, number][] = [
  ["Овощи и зелень", 3],
  ["Мясо и птица", 2],
  ["Рыба", 2],
  ["Молочные продукты и сыры", 2],
  ["Напитки", 1],
];

export function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Настройки" meta="Нормативы, по которым система ищет проблемы" />
      <Card className="mb-6 p-4">
        <SectionTitle aside="допустимый расход сверх ТТК">Допуски потерь по категориям</SectionTitle>
        <table className="w-full text-sm">
          <tbody>
            {TOLERANCES.map(([category, value]) => (
              <tr key={category} className="border-t border-slate-100">
                <td className="py-2">{category}</td>
                <td className="py-2 text-right">
                  <input
                    type="number"
                    defaultValue={value}
                    step={0.5}
                    min={0}
                    className="w-20 rounded-md border border-slate-300 px-2 py-1 text-right"
                    aria-label={`Допуск: ${category}`}
                  />{" "}
                  %
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-slate-500">Сейчас — отраслевые значения. Если в сети есть свои нормативы, их стоит внести.</p>
      </Card>
      <Card className="p-4">
        <SectionTitle>Целевой фудкост</SectionTitle>
        <label className="flex items-center justify-between text-sm">
          По сети
          <span>
            <input type="number" defaultValue={30} className="w-20 rounded-md border border-slate-300 px-2 py-1 text-right" aria-label="Целевой фудкост" /> %
          </span>
        </label>
        <p className="mt-3 text-xs text-slate-500">Используется для поиска блюд, цену которых стоит пересмотреть.</p>
      </Card>
    </div>
  );
}
