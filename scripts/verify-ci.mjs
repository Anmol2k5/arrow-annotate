#!/usr/bin/env node
// Verify a GitHub Actions workflow exists that runs on windows and executes
// lint + tests, and that no job is unconditionally forced to succeed.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const wfDir = join(root, ".github", "workflows");

const failures = [];

if (!existsSync(wfDir)) {
  failures.push("missing .github/workflows directory");
} else {
  const files = readdirSync(wfDir).filter((f) => /\.ya?ml$/.test(f));
  if (!files.length) failures.push("no workflow files found");

  let foundWindows = false;
  let foundTests = false;
  let foundLint = false;
  let unconditionalContinueOnError = false;

  for (const f of files) {
    const text = readFileSync(join(wfDir, f), "utf8");
    if (/runs-on:\s*.*windows/i.test(text)) foundWindows = true;
    if (/pytest/.test(text)) foundTests = true;
    if (/ruff/.test(text)) foundLint = true;
    // A job-level `continue-on-error: true` on every step would mask failures.
    if (/^\s*continue-on-error:\s*true\s*$/m.test(text) && !/^\s*continue-on-error:\s*false/m.test(text)) {
      unconditionalContinueOnError = true;
    }
  }

  if (!foundWindows) failures.push("no workflow runs on a windows runner");
  if (!foundTests) failures.push("no workflow runs pytest");
  if (!foundLint) failures.push("no workflow runs ruff");
  if (unconditionalContinueOnError) failures.push("a workflow sets continue-on-error: true unconditionally");
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ci verification passed");
