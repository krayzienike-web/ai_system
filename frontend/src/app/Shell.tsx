import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Building2,
  CalendarRange,
  Database,
  FileBarChart,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  Lightbulb,
  ListChecks,
  LogOut,
  type LucideIcon,
  Settings,
  Sparkles,
} from "lucide-react";
import { motion } from "motion/react";
import { useEffect } from "react";

import { tokens } from "../api/client";
import { useMe } from "../api/hooks";
import { ROLE_LABELS } from "../api/types";
import { Logo, LogoMark } from "../brand/Logo";
import { cx } from "../ds/primitives";
import { PERIOD } from "../mock/data";
import { usePrototype } from "../state/prototype";
import { ChatDrawer } from "./chat/ChatDrawer";
import { useInboxCount, useOpenTaskCount } from "./counts";

interface NavItem {
  to: string;
  title: string;
  short: string; // label in the phone tab bar
  Icon: LucideIcon;
  badge?: "tasks" | "inbox";
  mobile?: boolean; // shown in the phone tab bar
}

const DIRECTOR_NAV: NavItem[] = [
  { to: "/", title: "Моя неделя", short: "Неделя", Icon: CalendarRange, mobile: true },
  { to: "/tasks", title: "Задачи", short: "Задачи", Icon: ListChecks, badge: "tasks", mobile: true },
  { to: "/findings", title: "Все находки", short: "Находки", Icon: Lightbulb, mobile: true },
  { to: "/data", title: "Данные", short: "Данные", Icon: Database },
];

const HQ_NAV: NavItem[] = [
  { to: "/", title: "Сеть", short: "Сеть", Icon: LayoutDashboard, mobile: true },
  { to: "/decisions", title: "Ждут решения", short: "Решения", Icon: Inbox, badge: "inbox", mobile: true },
  { to: "/findings", title: "Находки", short: "Находки", Icon: Lightbulb, mobile: true },
  { to: "/checks", title: "Проверки", short: "Проверки", Icon: FlaskConical },
  { to: "/tasks", title: "Задачи", short: "Задачи", Icon: ListChecks, badge: "tasks" },
  { to: "/restaurants", title: "Рестораны", short: "Рестораны", Icon: Building2 },
  { to: "/report", title: "Отчет для собственника", short: "Отчет", Icon: FileBarChart },
  { to: "/data", title: "Данные", short: "Данные", Icon: Database },
  { to: "/settings", title: "Нормы и настройки", short: "Настройки", Icon: Settings },
];

function Badge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <motion.span
      key={count}
      initial={{ scale: 1.5 }}
      animate={{ scale: 1 }}
      transition={{ type: "spring", stiffness: 500, damping: 18 }}
      className="num ml-auto grid min-w-5 place-items-center rounded-full bg-spark px-1.5 text-[11px] font-semibold text-ink"
    >
      {count}
    </motion.span>
  );
}

export function Shell() {
  const { data: me, isError } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { openChat } = usePrototype();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const counts = { tasks: useOpenTaskCount(), inbox: useInboxCount() };

  function logout() {
    tokens.clear();
    queryClient.clear();
    void navigate({ to: "/login" });
  }

  useEffect(() => {
    if (isError) logout();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isError]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openChat();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openChat]);

  if (!me) return null;
  const isDirector = me.role === "restaurant_director";
  const nav = isDirector ? DIRECTOR_NAV : HQ_NAV;
  const isActive = (to: string) => (to === "/" ? pathname === "/" : pathname.startsWith(to));

  return (
    <div className="min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] flex-col bg-ink text-white lg:flex">
        <div className="px-5 pt-5 pb-6">
          <span className="inline-flex items-center gap-2.5">
            <LogoMark inverted />
            <span className="font-display text-[17px] font-semibold tracking-tight">SousChef</span>
            <span className="rounded-md border border-white/25 px-1 py-px text-[10px] font-semibold">AI</span>
          </span>
        </div>
        <nav className="flex-1 space-y-0.5 px-3" aria-label="Основное меню">
          {nav.map(({ to, title, Icon, badge }) => (
            <Link
              key={to}
              to={to}
              className={cx(
                "relative flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm transition-colors",
                isActive(to) ? "text-white" : "text-white/65 hover:bg-white/5 hover:text-white",
              )}
            >
              {isActive(to) && (
                <motion.span
                  layoutId="nav-active"
                  className="absolute inset-0 rounded-[10px] bg-brand"
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <Icon size={18} strokeWidth={1.75} className="relative" />
              <span className="relative">{title}</span>
              {badge && (
                <span className="relative ml-auto">
                  <Badge count={counts[badge]} />
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="m-3 rounded-[14px] bg-white/5 p-4">
          <div className="text-sm font-medium">{me.full_name}</div>
          <div className="text-xs text-white/60">{me.restaurant ? me.restaurant.name : ROLE_LABELS[me.role]}</div>
          <button onClick={logout} className="mt-3 inline-flex items-center gap-1.5 text-xs text-white/60 hover:text-white">
            <LogOut size={13} /> Выйти
          </button>
        </div>
      </aside>

      <div className="lg:pl-[248px]">
        {/* Top bar */}
        <header className="sticky top-0 z-20 border-b border-line bg-paper/85 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-3 px-4 sm:px-6 lg:px-8">
            <span className="lg:hidden">
              <Logo compact />
            </span>
            <div className="hidden min-w-0 items-center gap-2 text-sm text-ink-2 sm:flex">
              <span className="font-medium text-ink">Неделя {PERIOD.week}</span>
              <span className="text-ink-3">·</span>
              <span>данные обновлены {PERIOD.dataUntil.slice(0, 5)}</span>
              <span className="rounded-full bg-spark/25 px-2 py-0.5 text-[11px] font-medium text-ink">Прототип · демо-данные</span>
            </div>
            <button
              type="button"
              onClick={() => openChat()}
              className="group ml-auto inline-flex h-9 items-center gap-2 rounded-full border border-line-strong bg-surface pr-2 pl-3 text-sm text-ink-2 shadow-sm transition hover:border-brand hover:text-ink"
            >
              <Sparkles size={15} className="text-brand" />
              <span>Спросить су-шефа</span>
              <kbd className="hidden rounded-md bg-paper px-1.5 py-0.5 text-[11px] text-ink-3 sm:inline">Ctrl K</kbd>
            </button>
            <button onClick={logout} className="text-ink-3 hover:text-ink lg:hidden" aria-label="Выйти">
              <LogOut size={18} />
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-[1280px] px-4 pt-6 pb-28 sm:px-6 lg:px-8 lg:pb-12">
          <Outlet />
        </main>
      </div>

      {/* Phone tab bar */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 grid border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
        style={{ gridTemplateColumns: `repeat(${nav.filter((n) => n.mobile).length + 1}, 1fr)` }}
        aria-label="Меню"
      >
        {nav
          .filter((n) => n.mobile)
          .map(({ to, short, Icon, badge }) => (
            <Link
              key={to}
              to={to}
              className={cx("relative flex flex-col items-center gap-0.5 py-2 text-[11px]", isActive(to) ? "text-brand-strong" : "text-ink-3")}
            >
              <Icon size={20} strokeWidth={1.75} />
              {short}
              {badge && counts[badge] > 0 && (
                <span className="num absolute top-1 right-1/2 translate-x-4 rounded-full bg-spark px-1 text-[10px] font-semibold text-ink">
                  {counts[badge]}
                </span>
              )}
            </Link>
          ))}
        <Link
          to={isDirector ? "/data" : "/restaurants"}
          className={cx(
            "flex flex-col items-center gap-0.5 py-2 text-[11px]",
            isActive(isDirector ? "/data" : "/restaurants") ? "text-brand-strong" : "text-ink-3",
          )}
        >
          {isDirector ? <Database size={20} strokeWidth={1.75} /> : <Building2 size={20} strokeWidth={1.75} />}
          {isDirector ? "Данные" : "Рестораны"}
        </Link>
      </nav>

      <ChatDrawer />
    </div>
  );
}
