import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";

import { tokens } from "./api/client";
import { HomePage } from "./pages/Home";
import { Layout } from "./pages/Layout";
import { LoginPage } from "./pages/Login";
import { PlaceholderPage } from "./pages/Placeholder";
import { RestaurantsPage } from "./pages/Restaurants";
import { SECTIONS } from "./sections";

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
const restaurantsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/restaurants",
  component: RestaurantsPage,
});
const placeholderRoutes = SECTIONS.filter((s) => s.stage).map((section) =>
  createRoute({
    getParentRoute: () => appRoute,
    path: section.path,
    component: () => <PlaceholderPage section={section} />,
  }),
);

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([homeRoute, restaurantsRoute, ...placeholderRoutes]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
