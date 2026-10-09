#!/usr/bin/env node
// Verify required documentation files exist and contain substantive content.
import { readFileSync, existsSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const required = [
  "README.md",
  "AUDIT_REPORT.md",
  "IMPLEMENTATION_REPORT.md",
  "TEST_RESULTS.md",
  "docs/current-architecture.md",
  "docs/security-audit.md",
  "docs/development.md",
  "docs/testing.md",
  "docs/troubleshooting.md",
];

const failures = [];
const MIN_LINES = 10;

for (const rel of required) {
  const p = join(root, rel);
  if (!existsSync(p)) {
    failures.push(`missing: ${rel}`);
    continue;
  }
  if (statSync(p).size === 0) {
    failures.push(`empty: ${rel}`);
    continue;
  }
  const lines = readFileSync(p, "utf8").split(/\r?\n/).length;
  if (lines < MIN_LINES) failures.push(`too short (${lines} lines): ${rel}`);
}

// README must cover install + usage + extension setup.
const readme = existsSync(join(root, "README.md")) ? readFileSync(join(root, "README.md"), "utf8") : "";
for (const kw of ["install", "extension", "usage", "privacy"]) {
  if (!new RegExp(kw, "i").test(readme)) failures.push(`README.md does not mention "${kw}"`);
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("docs verification passed");
