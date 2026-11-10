/**
 * Where to return after signing in: only a path of this app («/checks/…»), never another site («//evil.com»,
 * «https://…», «/\\evil.com») and never the login itself (pre-pilot review 10.11.2026, p. 5).
 */
export function safeNext(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return undefined;
  if ([...value].some((c) => c.charCodeAt(0) < 32) || value.startsWith("/login")) return undefined;
  return value;
}
