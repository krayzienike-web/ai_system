import { useMe, useRestaurants } from "../api/hooks";

export function HomePage() {
  const { data: me } = useMe();
  const { data: restaurants } = useRestaurants();
  if (!me) return null;

  const isDirector = me.role === "restaurant_director";
  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-semibold">{isDirector ? me.restaurant?.name : "Сеть ресторанов"}</h1>
      <div className="rounded-xl bg-white p-6 shadow-sm">
        {isDirector ? (
          <p>
            Здесь появится сводка по вашему ресторану: карта процессов, проблемы и возможности с оценкой в ₽ и
            сравнение со средним по сети.
          </p>
        ) : (
          <p>
            Ресторанов в сети: <b>{restaurants?.length ?? "…"}</b>. Здесь появятся «деньги на столе», сравнение
            ресторанов и главные инсайты.
          </p>
        )}
      </div>
    </div>
  );
}
