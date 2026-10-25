import { createMemoryHistory, createRootRoute, createRoute, createRouter, Navigate, redirect } from "@tanstack/react-router";
import type { ComponentType } from "react";

import { DEMO, tokens } from "./api/client";
import { DataPage } from "./app/DataPage";
import { DesignSystemPage } from "./app/DesignSystemPage";
import { WeekView } from "./app/director/Week";
import { FindingPage } from "./app/findings/FindingPage";
import { FindingsPage } from "./app/findings/FindingsPage";
import { CheckPage, NewCheckPage } from "./app/hq/Checks";
import { DecisionsPage } from "./app/hq/Decisions";
import { NetworkPage } from "./app/hq/Network";
import { ReportPage } from "./app/hq/Report";
import { RestaurantPage, RestaurantsPage } from "./app/hq/Restaurants";
import { SettingsPage } from "./app/hq/Settings";
import { Shell } from "./app/Shell";
import { TasksPage } from "./app/TasksPage";
import { useViewer } from "./lib/useViewer";
import { LoginPage } from "./pages/Login";

/** Screens for the management company only. The API refuses them to a director; the UI never dead-ends there. */
function hqOnly(Page: ComponentType) {
  return function HqOnly() {
    const viewer = useViewer();
    if (!viewer) return null;
    return viewer.isHq ? <Page /> : <Navigate to="/" />;
  };
}

function Home() {
  const viewer = useViewer();
  if (!viewer) return null;
  if (viewer.isHq) return <NetworkPage />;
  return viewer.restaurantCode ? <WeekView code={viewer.restaurantCode} /> : null;
}

const rootRoute = createRootRoute();
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: LoginPage });
const designRoute = createRoute({ getParentRoute: () => rootRoute, path: "/design", component: DesignSystemPage });
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  component: Shell,
  beforeLoad: () => {
    if (!tokens.access && !tokens.refresh) throw redirect({ to: "/login" });
  },
});

const homeRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: Home });
const findingsRoute = createRoute({ getParentRoute: () => appRoute, path: "/findings", component: FindingsPage });
const findingRoute = createRoute({ getParentRoute: () => appRoute, path: "/findings/$findingId", component: FindingPage });
const tasksRoute = createRoute({ getParentRoute: () => appRoute, path: "/tasks", component: TasksPage });
const dataRoute = createRoute({ getParentRoute: () => appRoute, path: "/data", component: DataPage });
const decisionsRoute = createRoute({ getParentRoute: () => appRoute, path: "/decisions", component: hqOnly(DecisionsPage) });
// Checks live inside findings now (each check is opened from its finding); the old list address leads there.
const checksRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/checks",
  beforeLoad: () => {
    throw redirect({ to: "/findings" });
  },
});
const checkRoute = createRoute({ getParentRoute: () => appRoute, path: "/checks/$checkId", component: hqOnly(CheckPage) });
const newCheckRoute = createRoute({ getParentRoute: () => appRoute, path: "/checks/new/$findingId", component: hqOnly(NewCheckPage) });
const restaurantsRoute = createRoute({ getParentRoute: () => appRoute, path: "/restaurants", component: hqOnly(RestaurantsPage) });
const restaurantRoute = createRoute({ getParentRoute: () => appRoute, path: "/restaurants/$code", component: hqOnly(RestaurantPage) });
const reportRoute = createRoute({ getParentRoute: () => appRoute, path: "/report", component: hqOnly(ReportPage) });
const settingsRoute = createRoute({ getParentRoute: () => appRoute, path: "/settings", component: hqOnly(SettingsPage) });

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
    settingsRoute,
  ]),
]);

// The standalone demo runs inside a sandboxed frame where URL paths are not ours: keep history in memory.
export const router = createRouter({
  routeTree,
  scrollRestoration: true,
  // An unknown address leads home instead of an empty "not found" page.
  defaultNotFoundComponent: () => <Navigate to="/" />,
  ...(DEMO ? { history: createMemoryHistory({ initialEntries: ["/login"] }) } : {}),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
