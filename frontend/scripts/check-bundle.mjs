// The production build must not carry the prototype: no recorded answers, no demo logins or password
// (architecture review 27.10.2026, p. 1). Run after `npm run build`.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const FORBIDDEN = ["demo.local", "demo12345", "recorded_for"];
const dir = "dist/assets";
const found = readdirSync(dir)
  .filter((f) => f.endsWith(".js"))
  .flatMap((f) => FORBIDDEN.filter((s) => readFileSync(join(dir, f), "utf8").includes(s)).map((s) => `${f}: ${s}`));
if (found.length) {
  console.error(`The production bundle carries the prototype:\n${found.join("\n")}`);
  process.exit(1);
}
console.log("Production bundle: no demo data.");
