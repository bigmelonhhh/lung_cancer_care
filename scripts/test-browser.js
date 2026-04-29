#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");
const managePyPath = path.join(repoRoot, "manage.py");

if (!fs.existsSync(managePyPath)) {
  console.error(`[test:browser] manage.py not found: ${managePyPath}`);
  process.exit(1);
}

const pythonCmd = process.env.PYTHON || "python";

const importCheck = spawnSync(
  pythonCmd,
  [
    "-c",
    "import playwright; from playwright.sync_api import sync_playwright; print('playwright import ok')",
  ],
  {
    cwd: repoRoot,
    encoding: "utf8",
    shell: false,
  }
);

if (importCheck.status !== 0) {
  console.error("[test:browser] Python Playwright is not installed.");
  console.error("[test:browser] Run: pip install -r requirements.txt");
  if (importCheck.stderr) console.error(importCheck.stderr.trim());
  process.exit(importCheck.status || 1);
}

const extraArgs = process.argv.slice(2);
const hasDbFlags = extraArgs.some((arg) => arg === "--keepdb" || arg === "--noinput");
const defaultArgs = hasDbFlags ? [] : ["--keepdb", "--noinput"];
const args = ["manage.py", "test", ...defaultArgs, "tests.browser", ...extraArgs];

console.log(`[test:browser] Running: ${pythonCmd} ${args.join(" ")}`);

const result = spawnSync(pythonCmd, args, {
  cwd: repoRoot,
  stdio: "inherit",
  shell: process.platform === "win32",
});

if (result.error) {
  console.error(`[test:browser] Failed to run command: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
