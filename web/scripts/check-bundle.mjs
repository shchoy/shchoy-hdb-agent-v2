// Fails if anything secret or server-only leaked into the browser bundles. Run after `next build`.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const FORBIDDEN = ["ANTHROPIC", "sk-ant", "LANGSMITH", "PLG_API_URL", "127.0.0.1:8000", "X-PLG-User"];
const root = new URL("../.next/static", import.meta.url).pathname;

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else yield path;
  }
}

let scanned = 0;
const leaks = [];
try {
  for (const file of files(root)) {
    scanned += 1;
    const text = readFileSync(file, "latin1");
    for (const needle of FORBIDDEN) {
      if (text.toLowerCase().includes(needle.toLowerCase())) leaks.push(`${relative(root, file)}: ${needle}`);
    }
  }
} catch (error) {
  console.error(`check:bundle: cannot read ${root}. Run \`npm run build\` first.\n${error}`);
  process.exit(1);
}

if (scanned === 0) {
  console.error("check:bundle: .next/static is empty. Run `npm run build` first.");
  process.exit(1);
}
if (leaks.length > 0) {
  console.error(`check:bundle: forbidden strings in client bundles:\n  ${leaks.join("\n  ")}`);
  process.exit(1);
}
console.log(`check:bundle: ${scanned} files in .next/static, no forbidden strings.`);
