import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Building2,
  CalendarRange,
  Database,
  FlaskConical,
  LayoutDashboard,
  Lightbulb,
  ListTodo,
  LogOut,
  Menu,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import { type ComponentType, useEffect, useState } from "react";

import { tokens } from "../api/client";
import { useMe } from "../api/hooks";
import { ROLE_LABELS } from "../api/types";
import { ChatDrawer } from "../components/Chat";
import { Button, cx } from "../components/ui";
import { PRODUCT_NAME, PRODUCT_TAGLINE } from "../config";
import { usePrototype } from "../state/prototype";

interface NavItem {
  to: string;
  title: string;
  Icon: ComponentType<{ size?: number }>;
}

const DIRECTOR_NAV: NavItem[] = [
  { to: "/", title: "Сводка недели", Icon: CalendarRange },
  { to: "/tasks", title: "Мои задачи", Icon: ListTodo },
  { to: "/assistant", title: "Ассистент", Icon: Sparkles },
  { to: "/data", title: "Данные", Icon: Database },
];

const HQ_NAV: NavItem[] = [
  { to: "/", title: "Обзор сети", Icon: LayoutDashboard },
  { to: "/insights", title: "Инсайты", Icon: Lightbulb },
  { to: "/experiments", title: "Эксперименты", Icon: FlaskConical },
  { to: "/tasks", title: "Задачи", Icon: ListTodo },
  { to: "/restaurants", title: "Рестораны", Icon: Building2 },
  { to: "/assistant", title: "Ассистент", Icon: Sparkles },
  { to: "/data", title: "Данные", Icon: Database },
  { to: "/settings", title: "Настройки", Icon: Settings },
];

export function Layout() {
  const { data: me, isError } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { openChat } = usePrototype();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // The mobile menu belongs to the page it was opened on, so navigating closes it.
  const [menuOpenOn, setMenuOpenOn] = useState<string | null>(null);
  const menuOpen = menuOpenOn === pathname;
  const setMenuOpen = (open: boolean) => setMenuOpenOn(open ? pathname : null);

  function logout() {
    tokens.clear();
    queryClient.clear();
    void navigate({ to: "/login" });
  }

  useEffect(() => {
    if (isError) logout();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isError]);

  if (!me) return null;
  const nav = me.role === "restaurant_director" ? DIRECTOR_NAV : HQ_NAV;

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 p-4">
        <div className="font-semibold text-slate-900">{PRODUCT_NAME}</div>
        <div className="text-xs text-slate-500">{PRODUCT_TAGLINE}</div>
      </div>
      <nav className="flex-1 space-y-0.5 p-2" aria-label="Основное меню">
        {nav.map(({ to, title, Icon }) => (
          <Link
            key={to}
            to={to}
            className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
            activeProps={{ className: "bg-slate-100 font-medium text-slate-900" }}
            activeOptions={{ exact: to === "/" }}
          >
            <Icon size={16} />
            {title}
          </Link>
        ))}
      </nav>
      <div className="border-t border-slate-200 p-4 text-sm">
        <div className="font-medium text-slate-900">{me.full_name}</div>
        <div className="text-slate-500">{me.restaurant ? me.restaurant.name : ROLE_LABELS[me.role]}</div>
        <button onClick={logout} className="mt-2 inline-flex items-center gap-1.5 text-slate-600 hover:text-slate-900">
          <LogOut size={14} /> Выйти
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-slate-200 bg-white lg:block">{sidebar}</aside>

      {menuOpen && (
        <div className="fixed inset-0 z-30 bg-slate-900/20 lg:hidden" onClick={() => setMenuOpen(false)}>
          <aside className="h-full w-64 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b border-slate-200 bg-white/90 px-4 py-2 backdrop-blur">
          <div className="flex items-center gap-2">
            <Button variant="ghost" className="lg:hidden" onClick={() => setMenuOpen(!menuOpen)} aria-label="Меню">
              {menuOpen ? <X size={18} /> : <Menu size={18} />}
            </Button>
            <span className="font-semibold lg:hidden">{PRODUCT_NAME}</span>
            <span className="hidden rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-900 sm:inline">
              Прототип · демонстрационные данные
            </span>
          </div>
          <Button onClick={() => openChat()}>
            <Sparkles size={14} /> <span className="hidden sm:inline">Спросить ИИ</span>
          </Button>
        </header>
        <main className={cx("px-4 py-6 sm:px-6 lg:px-8")}>
          <Outlet />
        </main>
      </div>
      <ChatDrawer />
    </div>
  );
}
