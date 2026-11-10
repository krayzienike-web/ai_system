// Pre-pilot review 10.11.2026 (TC-UI-31, frontend pp. 3–4, 6): what the screens show when the server fails —
// rendered on the server side of React with the queries already settled, so no network and no browser are needed.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouteComponent,
  RouterProvider,
} from "@tanstack/react-router";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { AppContext, Me } from "../api/types";
import { LoadError } from "../ds/primitives";
import { UiProvider } from "../state/ui";
import { WeekView } from "./director/Week";
import { FindingPage } from "./findings/FindingPage";
import { NetworkPage } from "./hq/Network";
import { RestaurantsPage } from "./hq/Restaurants";
import { NoDataYet } from "./NoDataYet";
import { Shell } from "./Shell";
import { TasksPage } from "./TasksPage";

const DIRECTOR: Me = {
  id: "u1",
  email: "director1@demo.local",
  full_name: "Директор",
  tenant_id: "t1",
  role: "restaurant_director",
  restaurant: { id: "r1", code: "R01", name: "Ресторан 1" },
  permissions: [],
};
const HQ: Me = { ...DIRECTOR, role: "hq_admin", restaurant: null, permissions: ["network.compare", "data.upload"] };
const SERVER_DOWN = new ApiError(500, "Сервер не ответил — попробуйте еще раз");

type Seed = [readonly unknown[], { data: unknown } | { error: Error }];

/** The cache as it is after the requests settled; a failed query is not retried on mount (as after its retries). */
function client(seeds: Seed[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity } } });
  for (const [key, state] of seeds) {
    if ("data" in state) qc.setQueryData(key, state.data);
    else
      qc.getQueryCache()
        .build(qc, { queryKey: key })
        .setState({ status: "error", error: state.error, fetchStatus: "idle", errorUpdatedAt: 1, fetchFailureCount: 1 });
  }
  return qc;
}

/** Renders `Page` at `path` inside a router shaped like the app's (a pathless «app» layout). */
async function render(Page: RouteComponent, path: string, seeds: Seed[], Layout: RouteComponent = Outlet) {
  const root = createRootRoute();
  const app = createRoute({ getParentRoute: () => root, id: "app", component: Layout });
  const pages = ["/", "/tasks", "/restaurants", "/findings/$findingId", "/data", "/login"].map((p) =>
    createRoute({ getParentRoute: () => app, path: p, component: Page }),
  );
  const router = createRouter({
    routeTree: root.addChildren([app.addChildren(pages)]),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  await router.load();
  return renderToString(
    <QueryClientProvider client={client(seeds)}>
      <UiProvider>
        <RouterProvider router={router} />
      </UiProvider>
    </QueryClientProvider>,
  );
}

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/g, " ").replace(/\s+/g, " ");
const retryButton = (html: string) => /<button[^>]*>\s*Повторить\s*<\/button>/.test(html);

const context = (data_until: string | null) => ({ data_until }) as unknown as AppContext;

beforeEach(() => {
  const store = new Map<string, string>([["fai.access", "a1"]]);
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => store.set(k, v),
    removeItem: (k: string) => store.delete(k),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("the shell when «who is here» fails (TC-UI-31, p. 3)", () => {
  it("a failed server says so with «Повторить», never a blank page", async () => {
    const html = await render(Outlet, "/", [[["me"], { error: SERVER_DOWN }]], Shell);
    expect(text(html)).toContain("Не получилось открыть SousChef AI");
    expect(text(html)).toContain("Сервер не ответил");
    expect(retryButton(html)).toBe(true);
  });

  it("a lost connection says «no connection»", async () => {
    const html = await render(Outlet, "/", [[["me"], { error: new ApiError(0, "Нет связи с сервером") }]], Shell);
    expect(text(html)).toContain("Нет связи с сервером");
  });

  it("an ended session draws nothing: it leads to the login instead", async () => {
    const html = await render(Outlet, "/", [[["me"], { error: new ApiError(401, "Сессия закончилась — войдите снова") }]], Shell);
    expect(text(html)).not.toContain("Не получилось открыть");
    expect(text(html).trim()).toBe("");
  });
});

describe("a screen that failed to load says so and offers «Повторить» (TC-UI-31, p. 4)", () => {
  it("«Задачи» of a director", async () => {
    const html = await render(TasksPage, "/tasks", [
      [["me"], { data: DIRECTOR }],
      [["tasks", false], { error: SERVER_DOWN }],
    ]);
    expect(text(html)).toContain("Не получилось загрузить задачи");
    expect(text(html)).toContain("Сервер не ответил");
    expect(retryButton(html)).toBe(true);
  });

  it("«Рестораны» of the HQ", async () => {
    const html = await render(RestaurantsPage, "/restaurants", [
      [["me"], { data: HQ }],
      [["overview", "restaurants"], { error: SERVER_DOWN }],
    ]);
    expect(text(html)).toContain("Не получилось загрузить рестораны");
    expect(retryButton(html)).toBe(true);
  });

  it("«Неделя»: 404 is «Ресторан не найден», any other failure is not", async () => {
    const Week = () => <WeekView code="R01" />;
    const base: Seed[] = [
      [["me"], { data: DIRECTOR }],
      [["context"], { data: context("2026-10-18") }],
    ];
    const missing = await render(Week, "/", [...base, [["overview", "restaurant", "R01"], { error: new ApiError(404, "Ресторан не найден") }]]);
    expect(text(missing)).toContain("Ресторан не найден");
    expect(retryButton(missing)).toBe(false);
    const down = await render(Week, "/", [...base, [["overview", "restaurant", "R01"], { error: SERVER_DOWN }]]);
    expect(text(down)).toContain("Не получилось загрузить неделю");
    expect(text(down)).not.toContain("Ресторан не найден");
    expect(retryButton(down)).toBe(true);
  });

  it("a finding: 404 and 403 are «Находка не найдена», a failure is «Повторить»", async () => {
    const base: Seed[] = [[["me"], { data: DIRECTOR }]];
    for (const status of [404, 403]) {
      const html = await render(FindingPage, "/findings/f1", [...base, [["finding", "f1"], { error: new ApiError(status, "Нет доступа") }]]);
      expect(text(html)).toContain("Находка не найдена");
      expect(retryButton(html)).toBe(false);
    }
    const html = await render(FindingPage, "/findings/f1", [...base, [["finding", "f1"], { error: SERVER_DOWN }]]);
    expect(text(html)).toContain("Не получилось загрузить находку");
    expect(retryButton(html)).toBe(true);
  });

  it("a crash of the code is not shown as words for people, only the server's answers are", async () => {
    const html = renderToString(<LoadError error={new TypeError("Cannot read properties of undefined")} />);
    expect(text(html)).toContain("Обновите страницу чуть позже");
    expect(text(html)).not.toContain("Cannot read");
  });
});

describe("a network without data says so (TC-UI-31, p. 6)", () => {
  it("«Сеть» of the HQ leads to «Данные»", async () => {
    const html = await render(NetworkPage, "/", [
      [["me"], { data: HQ }],
      [["context"], { data: context(null) }],
    ]);
    expect(text(html)).toContain("Данных пока нет");
    expect(html).toMatch(/<a[^>]*href="\/data"[^>]*>.*Загрузить данные/);
    expect(text(html)).not.toContain("Проблем выше нормы нет");
  });

  it("«Неделя» of a director has no upload button: the HQ loads the data", async () => {
    const html = await render(() => <WeekView code="R01" />, "/", [
      [["me"], { data: DIRECTOR }],
      [["context"], { data: context(null) }],
      [["overview", "restaurant", "R01"], { error: SERVER_DOWN }],
    ]);
    expect(text(html)).toContain("Данных пока нет");
    expect(text(html)).toContain("Управляющая компания еще не загрузила");
    expect(text(html)).not.toContain("Загрузить данные");
  });

  it("with data — nothing", async () => {
    const html = await render(() => <NoDataYet canUpload />, "/", [[["context"], { data: context("2026-10-18") }]]);
    expect(text(html).trim()).toBe("");
    const unknown = await render(() => <NoDataYet canUpload />, "/", []); // context not known yet: no flash of «нет данных»
    expect(text(unknown).trim()).toBe("");
  });
});
