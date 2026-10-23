import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useNavigate } from "@tanstack/react-router";

import { tokens } from "../api/client";
import { useMe } from "../api/hooks";
import { ROLE_LABELS } from "../api/types";
import { SECTIONS } from "../sections";

export function Layout() {
  const { data: me, isError } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  function logout() {
    tokens.clear();
    queryClient.clear();
    void navigate({ to: "/login" });
  }

  if (isError) {
    logout();
    return null;
  }

  const isHq = me?.role !== "restaurant_director";
  const sections = SECTIONS.filter((s) => s.path !== "/restaurants" || isHq);

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <aside className="flex w-64 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-4">
          <div className="font-semibold">AI-центр франшизы</div>
          <div className="text-xs text-slate-500">AI-менеджер запасов · MVP</div>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {sections.map((s) => (
            <Link
              key={s.path}
              to={s.path}
              className="flex items-center justify-between rounded-md px-3 py-2 text-sm hover:bg-slate-100"
              activeProps={{ className: "bg-slate-100 font-medium" }}
              activeOptions={{ exact: s.path === "/" }}
            >
              <span>{s.title}</span>
              {s.stage && <span className="text-[10px] text-slate-400">скоро</span>}
            </Link>
          ))}
        </nav>
        {me && (
          <div className="border-t border-slate-200 p-4 text-sm">
            <div className="font-medium">{me.full_name}</div>
            <div className="text-slate-500">{ROLE_LABELS[me.role]}</div>
            {me.restaurant && <div className="text-slate-500">{me.restaurant.name}</div>}
            <button onClick={logout} className="mt-2 text-slate-600 underline">
              Выйти
            </button>
          </div>
        )}
      </aside>
      <main className="flex-1 p-8">
        <Outlet />
      </main>
    </div>
  );
}
