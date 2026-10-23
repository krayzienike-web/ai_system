import { useMe } from "../api/hooks";

export interface Viewer {
  isHq: boolean;
  /** Restaurant code of a director (R01…); null for HQ. */
  restaurantCode: string | null;
  name: string;
}

export function useViewer(): Viewer | null {
  const { data: me } = useMe();
  if (!me) return null;
  return {
    isHq: me.role !== "restaurant_director",
    restaurantCode: me.restaurant?.code ?? null,
    name: me.full_name,
  };
}

/** A director may see only their own restaurant; HQ sees everything. Mirrors the API rule. */
export const canSeeRestaurant = (viewer: Viewer, restaurantId: string | null) =>
  viewer.isHq || (restaurantId !== null && restaurantId === viewer.restaurantCode);
