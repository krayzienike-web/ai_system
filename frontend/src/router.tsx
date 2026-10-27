import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  type ErrorComponentProps,
  Navigate,
  redirect,
} from "@tanstack/react-router";
import { type ComponentType, lazy, Suspense } from "react";

import { DEMO, tokens } from "./api/client";
import { Shell } from "./app/Shell";
import { buttonClass, EmptyState, Skeleton } from "./ds/primitives";
import { useViewer } from "./lib/useViewer";
import { LoginPage } from "./pages/Login";

/** A screen loaded when first opened: the first visit downloads the shell, not every screen and chart library. */
function screen<M, K extends keyof M>(load: () => Promise<M>, name: K): () => React.JSX.Element {
  const Lazy = lazy(() => load().then((m) => ({ default: m[name] as ComponentType })));
  return function Screen() {
    return (
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Lazy />
      </Suspense>
    );
  };
}

const DataPage = screen(() => import("./app/DataPage"), "DataPage");
const DesignSystemPage = screen(() => import("./app/DesignSystemPage"), "DesignSystemPage");
const FindingPage = screen(() => import("./app/findings/FindingPage"), "FindingPage");
const FindingsPage = screen(() => import("./app/findings/FindingsPage"), "FindingsPage");
const CheckPage = screen(() => import("./app/hq/Checks"), "CheckPage");
const NewCheckPage = screen(() => import("./app/hq/Checks"), "NewCheckPage");
const DecisionsPage = screen(() => import("./app/hq/Decisions"), "DecisionsPage");
const NetworkPage = screen(() => import("./app/hq/Network"), "NetworkPage");
const ReportPage = screen(() => import("./app/hq/Report"), "ReportPage");
const ReviewPage = screen(() => import("./app/hq/Review"), "ReviewPage");
const ReviewFindingPage = screen(() => import("./app/hq/Review"), "ReviewFindingPage");
const RestaurantsPage = screen(() => import("./app/hq/Restaurants"), "RestaurantsPage");
const RestaurantPage = screen(() => import("./app/hq/Restaurants"), "RestaurantPage");
const SettingsPage = screen(() => import("./app/hq/Settings"), "SettingsPage");
const TasksPage = screen(() => import("./app/TasksPage"), "TasksPage");
const WeekView = lazy(() => import("./app/director/Week").then((m) => ({ default: m.WeekView })));

/** Screens for the management company only. The API refuses them to a director; the UI never dead-ends there. */
function hqOnly(Page: ComponentType) {
  return function HqOnly() {
    const viewer = useViewer();
    if (!viewer) return null;
    // By the permission the API checks (ADR 0007, p. 8), not by the role's name.
    return viewer.can("network.compare") ? <Page /> : <Navigate to="/" />;
  };
}

function Home() {
  const viewer = useViewer();
  if (!viewer) return null;
  if (viewer.isHq) return <NetworkPage />;
  return viewer.restaurantCode ? (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <WeekView code={viewer.restaurantCode} />
    </Suspense>
  ) : null;
}

const rootRoute = createRootRoute();
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});
const designRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/design",
  component: DesignSystemPage,
});
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  component: Shell,
  beforeLoad: () => {
    if (!tokens.access && !tokens.refresh) throw redirect({ to: "/login" });
  },
});

const homeRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: Home,
});
const findingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/findings",
  // «Сеть» opens a restaurant's findings in one process: /findings?restaurant=<id>&process=<process>.
  validateSearch: (search: Record<string, unknown>): { restaurant?: string; process?: string } => ({
    restaurant: typeof search.restaurant === "string" ? search.restaurant : undefined,
    process: typeof search.process === "string" ? search.process : undefined,
  }),
  component: FindingsPage,
});
const findingRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/findings/$findingId",
  component: FindingPage,
});
const tasksRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/tasks",
  component: TasksPage,
});
const dataRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/data",
  component: DataPage,
});
const decisionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/decisions",
  component: hqOnly(DecisionsPage),
});
// Checks live inside findings now (each check is opened from its finding); the old list address leads there.
const checksRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/checks",
  beforeLoad: () => {
    throw redirect({ to: "/findings" });
  },
});
const checkRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/checks/$checkId",
  component: hqOnly(CheckPage),
});
const newCheckRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/checks/new/$findingId",
  component: hqOnly(NewCheckPage),
});
const restaurantsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/restaurants",
  component: hqOnly(RestaurantsPage),
});
const restaurantRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/restaurants/$code",
  component: hqOnly(RestaurantPage),
});
const reportRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/report",
  component: hqOnly(ReportPage),
});
const reviewRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/review",
  component: hqOnly(ReviewPage),
});
const reviewFindingRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/review/$findingId",
  component: hqOnly(ReviewFindingPage),
});
const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: hqOnly(SettingsPage),
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  designRoute,
  appRoute.addChildren([
    homeRoute,
    findingsRoute,
    findingRoute,
    tasksRoute,
    dataRoute,
    decisionsRoute,
    checksRoute,
    newCheckRoute,
    checkRoute,
    restaurantsRoute,
    restaurantRoute,
    reportRoute,
    reviewRoute,
    reviewFindingRoute,
    settingsRoute,
  ]),
]);

// The standalone demo runs inside a sandboxed frame where URL paths are not ours: keep history in memory.
/** A screen that failed to load (a new version was deployed under an open tab, the network dropped). */
function ScreenError({ error }: ErrorComponentProps) {
  // A chunk of an older build is gone after a deploy: reloading picks up the new one.
  const stale = /dynamically imported module|Importing a module script failed|Failed to fetch/i.test(error instanceof Error ? error.message : String(error));
  return (
    <div className="mx-auto max-w-md py-16">
      <EmptyState
        title={stale ? "Вышла новая версия" : "Не получилось открыть экран"}
        action={
          <button type="button" onClick={() => window.location.reload()} className={buttonClass("primary")}>
            Обновить страницу
          </button>
        }
      >
        {stale ? "Обновите страницу, чтобы открыть экран в новой версии." : "Обновите страницу или попробуйте чуть позже."}
      </EmptyState>
    </div>
  );
}

export const router = createRouter({
  routeTree,
  scrollRestoration: true,
  defaultErrorComponent: ScreenError,
  // An unknown address leads home instead of an empty "not found" page.
  defaultNotFoundComponent: () => <Navigate to="/" />,
  ...(DEMO
    ? { history: createMemoryHistory({ initialEntries: ["/login"] }) }
    : {}),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
