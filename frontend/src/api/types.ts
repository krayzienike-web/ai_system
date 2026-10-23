export type Role = "hq_admin" | "hq_analyst" | "restaurant_director";

export const ROLE_LABELS: Record<Role, string> = {
  hq_admin: "Администратор УК",
  hq_analyst: "Аналитик УК",
  restaurant_director: "Директор ресторана",
};

export interface Me {
  id: string;
  email: string;
  full_name: string;
  tenant_id: string;
  role: Role;
  restaurant: { id: string; name: string } | null;
  permissions: string[];
}

export interface Restaurant {
  id: string;
  code: string;
  name: string;
  city: string | null;
  format: string | null;
  opened_on: string | null;
}
