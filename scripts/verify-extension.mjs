#!/usr/bin/env node
// Verify browser extension: manifest parses, permissions are scoped, JS files
// pass node --check, and the background state-machine tests pass.
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const extDir = join(root, "browser_extension");
const failures = [];

function mustExist(rel) {
  if (!existsSync(join(root, rel))) failures.push(`missing file: ${rel}`);
}
[
  "browser_extension/manifest.json",
  "browser_extension/background.js",
  "browser_extension/content.js",
  "browser_extension/popup.js",
  "browser_extension/popup.html",
].forEach(mustExist);

if (existsSync(join(extDir, "manifest.json"))) {
  try {
    const manifest = JSON.parse(readFileSync(join(extDir, "manifest.json"), "utf8"));
    if (manifest.manifest_version !== 3) failures.push(`manifest_version is ${manifest.manifest_version}, expected 3`);
    if (!manifest.name || !String(manifest.name).trim()) failures.push("manifest name is empty");
    if (/bluely/i.test(String(manifest.name))) failures.push(`stale Bluely branding in manifest name: ${manifest.name}`);
    const sw = manifest.background?.service_worker;
    if (sw !== undefined && typeof sw !== "string" && !Array.isArray(sw)) {
      failures.push("background.service_worker must be a string or array");
    }
    const cs = manifest.content_scripts ?? [];
    if (!cs.length) failures.push("no content_scripts declared");
    for (const entry of cs) {
      for (const f of entry.js ?? []) mustExist(`browser_extension/${f}`);
      for (const f of entry.css ?? []) mustExist(`browser_extension/${f}`);
    }
    if (typeof sw === "string") mustExist(`browser_extension/${sw}`);
    if (Array.isArray(sw)) for (const f of sw) mustExist(`browser_extension/${f}`);
    if (manifest.icons) for (const p of Object.values(manifest.icons)) mustExist(`browser_extension/${p}`);

    // Permission scoping: the extension must not request all_urls or broad
    // host access; content-script matches are limited to http/https.
    const permissions = manifest.permissions ?? [];
    for (const p of permissions) {
      if (!["activeTab", "storage", "tabs", "scripting"].includes(p)) {
        failures.push(`unexpected permission requested: ${p}`);
      }
    }
    const hosts = manifest.host_permissions ?? [];
    for (const h of hosts) {
      if (h === "<all_urls>" || /^(\*|http:\*|https:\*)/.test(h)) {
        failures.push(`overly broad host permission: ${h}`);
      }
      if (!/^(https?:\/\/(127\.0\.0\.1|localhost))/.test(h)) {
        failures.push(`host permission must be loopback-only: ${h}`);
      }
    }
    for (const entry of manifest.content_scripts ?? []) {
      for (const m of entry.matches ?? []) {
        if (m === "<all_urls>" || m.startsWith("file:") || m.startsWith("chrome")) {
          failures.push(`overly broad content-script match: ${m}`);
        }
      }
    }
  } catch (e) {
    failures.push(`manifest.json parse failed: ${e.message}`);
  }
}

for (const f of ["background.js", "content.js", "popup.js"]) {
  const p = join(extDir, f);
  if (!existsSync(p)) continue;
  try {
    execFileSync(process.execPath, ["--check", p], { stdio: "pipe" });
  } catch (e) {
    failures.push(`${f} syntax check failed: ${e.stderr?.toString() || e.message}`);
  }
}

// Behavioral tests for the service-worker state machine (auth, backoff,
// restart, inspect forwarding).
const testFile = join(extDir, "tests", "background.test.mjs");
if (existsSync(testFile)) {
  try {
    execFileSync(process.execPath, ["--test", testFile], { stdio: "pipe" });
  } catch (e) {
    const out = (e.stdout?.toString() || "") + (e.stderr?.toString() || "");
    failures.push(`background state-machine tests failed:\n${out.slice(-3000)}`);
  }
} else {
  failures.push("missing file: browser_extension/tests/background.test.mjs");
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("extension verification passed");
