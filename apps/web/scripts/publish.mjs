import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const source = resolve("out");
const target = resolve("../../services/api/static");
const legacy = new Set(["browser-auth.js", "app-runtime.js", "app-bootstrap.js"]);

await mkdir(target, { recursive: true });
for (const entry of await readdir(target, { withFileTypes: true })) {
  if (!legacy.has(entry.name)) {
    await rm(resolve(target, entry.name), { recursive: true, force: true });
  }
}
await cp(resolve(source, "_next"), resolve(target, "_next"), { recursive: true });
await cp(resolve(source, "index.html"), resolve(target, "index.html"));
for (const file of legacy) {
  await cp(resolve(source, file), resolve(target, file));
}
console.log(`Published static frontend to ${target}`);
