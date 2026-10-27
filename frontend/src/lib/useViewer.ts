import { useMe } from "../api/hooks";
import type { Permission } from "../api/schema";

export interface Viewer {
  isHq: boolean;
  /** Restaurant code of a director (R01…); null for HQ. */
  restaurantCode: string | null;
  name: string;
  /** HQ admin: may load network reference data (products, recipes…). */
  isAdmin: boolean;
  /** What the server lets this user do (`/auth/me`): buttons follow it, the API enforces it. */
  can: (permission: Permission) => boolean;
}

export function useViewer(): Viewer | null {
  const { data: me } = useMe();
  if (!me) return null;
  const granted = new Set<string>(me.permissions);
  return {
    isHq: me.role !== "restaurant_director",
    restaurantCode: me.restaurant?.code ?? null,
    name: me.full_name,
    isAdmin: me.role === "hq_admin",
    can: (permission) => granted.has(permission),
  };
}
