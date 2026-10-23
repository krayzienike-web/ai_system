import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { Me, Restaurant } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

export const useRestaurants = () =>
  useQuery({ queryKey: ["restaurants"], queryFn: () => api<Restaurant[]>("/restaurants") });
