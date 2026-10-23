import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";
import type { ComponentType } from "react";

import { tokens } from "./api/client";
import { EmptyState } from "./components/ui";
import { useViewer } from "./lib/useViewer";
import { DataPage } from "./pages/Data";
import { ExperimentPage, ExperimentsPage } from "./pages/Experiments";
import { FindingPage } from "./pages/Finding";
import { InsightsPage } from "./pages/Insights";
import { Layout } from "./pages/Layout";
import { LoginPage } from "./pages/Login";
import { AssistantPage, HomePage, SettingsPage } from "./pages/Misc";
import { RestaurantPage, RestaurantsPage } from "./pages/Restaurants";
import { TasksPage } from "./pages/Tasks";

/** Screens for the management company only; a director gets "not found", as with the API. */
function hqOnly(Page: ComponentType) {
  return function HqOnly() {
    const viewer = useViewer();
    if (!viewer) return null;
    return viewer.isHq ? <Page /> : <EmptyState title="Страница не найдена" />;
  };
}

const rootRoute = createRootRoute();

const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: LoginPage });

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  component: Layout,
  beforeLoad: () => {
    if (!tokens.access && !tokens.refresh) throw redirect({ to: "/login" });
  },
});

const homeRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: HomePage });
const insightsRoute = createRoute({ getParentRoute: () => appRoute, path: "/insights", component: hqOnly(InsightsPage) });
const findingRoute = createRoute({ getParentRoute: () => appRoute, path: "/insights/$findingId", component: FindingPage });
const experimentRoute = createRoute({ getParentRoute: () => appRoute, path: "/experiments/$experimentId", component: hqOnly(ExperimentPage) });
const tasksRoute = createRoute({ getParentRoute: () => appRoute, path: "/tasks", component: TasksPage });
const restaurantsRoute = createRoute({ getParentRoute: () => appRoute, path: "/restaurants", component: hqOnly(RestaurantsPage) });
const restaurantRoute = createRoute({ getParentRoute: () => appRoute, path: "/restaurants/$code", component: hqOnly(RestaurantPage) });
const assistantRoute = createRoute({ getParentRoute: () => appRoute, path: "/assistant", component: AssistantPage });
const dataRoute = createRoute({ getParentRoute: () => appRoute, path: "/data", component: DataPage });
const settingsRoute = createRoute({ getParentRoute: () => appRoute, path: "/settings", component: hqOnly(SettingsPage) });

const experimentsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/experiments",
  component: hqOnly(ExperimentsPage),
  validateSearch: (search: Record<string, unknown>): { draft?: string } =>
    typeof search.draft === "string" ? { draft: search.draft } : {},
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([
    homeRoute,
    insightsRoute,
    findingRoute,
    experimentsRoute,
    experimentRoute,
    tasksRoute,
    restaurantsRoute,
    restaurantRoute,
    assistantRoute,
    dataRoute,
    settingsRoute,
  ]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
