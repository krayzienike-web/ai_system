// Standalone demo mode (VITE_DEMO=1): the prototype runs without the backend, e.g. as a shared link.
// Mirrors the API's access rules: a director sees only their own restaurant.
import { RESTAURANTS } from "../mock/data";
import {
  DEMO_PRODUCTS,
  DEMO_TEMPLATES,
  demoAliasEdit,
  demoAliasRestaurant,
  demoAliases,
  demoBatchAction,
  demoBatchRestaurant,
  demoBatches,
  demoFreshness,
  demoMatch,
  demoUpload,
} from "./demoImports";
import { demoEngineParams } from "./demoEngine";
import { demoNorms } from "./demoNorms";
import { demoCheckedFindings, demoReview } from "./demoReview";
import { ApiError } from "./client";
import type { Me, Restaurant, Role } from "./types";

export const DEMO_PASSWORD = "demo12345";

const USERS: Record<string, { name: string; role: Role; code: string | null }> =
  {
    "admin@demo.local": {
      name: "Администратор УК",
      role: "hq_admin",
      code: null,
    },
    "analyst@demo.local": {
      name: "Аналитик УК",
      role: "hq_analyst",
      code: null,
    },
    "director1@demo.local": {
      name: "Директор R01",
      role: "restaurant_director",
      code: "R01",
    },
    "director2@demo.local": {
      name: "Директор R02",
      role: "restaurant_director",
      code: "R02",
    },
    "director3@demo.local": {
      name: "Директор R03",
      role: "restaurant_director",
      code: "R03",
    },
  };

export class DemoAuthError extends Error {}

function me(email: string): Me {
  const user = USERS[email];
  if (!user) throw new DemoAuthError("unknown user");
  const restaurant = user.code
    ? RESTAURANTS.find((r) => r.code === user.code)!
    : null;
  return {
    id: email,
    email,
    full_name: user.name,
    tenant_id: "demo",
    role: user.role,
    restaurant: restaurant
      ? { id: restaurant.code, code: restaurant.code, name: restaurant.name }
      : null,
    permissions: [],
  };
}

/** Handles the few endpoints the prototype calls. The "token" is simply the user's email. */
export function demoRequest(
  path: string,
  init: RequestInit,
  token: string | null,
): unknown | Promise<unknown> {
  if (path === "/auth/login") {
    const { email, password } = JSON.parse(String(init.body)) as {
      email: string;
      password: string;
    };
    const key = email.trim().toLowerCase();
    if (!USERS[key] || password !== DEMO_PASSWORD)
      throw new DemoAuthError("invalid credentials");
    return { access_token: key, refresh_token: key, token_type: "bearer" };
  }
  if (!token) throw new DemoAuthError("not authenticated");
  const viewer = me(token);
  if (path === "/auth/me") return viewer;
  if (path === "/restaurants") {
    return RESTAURANTS.filter(
      (r) => !viewer.restaurant || r.code === viewer.restaurant.code,
    ).map(
      (r): Restaurant => ({
        id: r.code,
        code: r.code,
        name: r.name,
        city: r.city,
        format: null,
        opened_on: null,
      }),
    );
  }
  const own = viewer.restaurant?.code ?? null;
  if (path === "/imports/templates") return DEMO_TEMPLATES;
  if (path === "/imports/freshness") return demoFreshness(own);
  if (path === "/imports" && init.method === "POST") {
    // Like the server: network reference data is HQ's, a director uploads only for their restaurant.
    const target = (init.body as FormData).get("restaurant_id") || null;
    if (own && target !== own)
      throw new ApiError(403, "Можно загружать данные только своего ресторана");
    return demoUpload(init.body as FormData);
  }
  // A director does not see other restaurants' files and network names (RLS on the server): not found.
  const batchId = /^\/imports\/([^/]+)\/(match|publish|rollback|reprocess)$/.exec(path)?.[1];
  if (own && batchId && demoBatchRestaurant(batchId) !== own)
    throw new ApiError(404, "Загрузка не найдена");
  const aliasId = /^\/aliases\/([^/]+)$/.exec(path)?.[1];
  if (own && aliasId && demoAliasRestaurant(aliasId) !== own)
    throw new ApiError(404, "Соответствие не найдено");
  if (path === "/imports") return demoBatches(own);
  if (path === "/catalog/product") return DEMO_PRODUCTS;
  if (path === "/findings") return demoCheckedFindings(own);
  if (
    path === "/analytics/run" ||
    /^\/findings(\?review=|\/[^/]+\/(verification|review)$)/.test(path)
  )
    return demoReview(
      path,
      init,
      viewer.role !== "restaurant_director",
      viewer.role === "hq_admin",
      viewer.full_name,
    );
  if (path === "/settings/engine")
    return demoEngineParams(init, viewer.role === "hq_admin");
  if (path === "/settings/norms")
    return demoNorms(init, viewer.role === "hq_admin");
  if (path === "/aliases") return demoAliases(own);
  const alias = /^\/aliases\/([^/]+)$/.exec(path);
  if (alias) return demoAliasEdit(alias[1]!, init);
  if (path.startsWith("/catalog/")) return [];
  const matching = /^\/imports\/([^/]+)\/match$/.exec(path);
  if (matching) return demoMatch(matching[1]!, String(init.body));
  const action = /^\/imports\/([^/]+)\/(publish|rollback|reprocess)$/.exec(
    path,
  );
  if (action)
    return demoBatchAction(
      action[1]!,
      action[2] as "publish" | "rollback" | "reprocess",
    );
  throw new Error(`Demo mode: ${path} is not available`);
}
