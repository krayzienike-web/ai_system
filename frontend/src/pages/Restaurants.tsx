import { useRestaurants } from "../api/hooks";

export function RestaurantsPage() {
  const { data, isLoading } = useRestaurants();
  return (
    <div className="max-w-4xl space-y-4">
      <h1 className="text-2xl font-semibold">Рестораны</h1>
      {isLoading ? (
        <p className="text-slate-500">Загрузка…</p>
      ) : (
        <table className="w-full overflow-hidden rounded-xl bg-white text-sm shadow-sm">
          <thead className="bg-slate-100 text-left text-slate-600">
            <tr>
              <th className="px-4 py-2">Код</th>
              <th className="px-4 py-2">Название</th>
              <th className="px-4 py-2">Город</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((r) => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-4 py-2 font-mono">{r.code}</td>
                <td className="px-4 py-2">{r.name}</td>
                <td className="px-4 py-2">{r.city ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
