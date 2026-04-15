#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");
const managePyPath = path.join(repoRoot, "manage.py");

if (!fs.existsSync(managePyPath)) {
  console.error(`[test:ui] manage.py not found: ${managePyPath}`);
  process.exit(1);
}

const pythonCmd = process.env.PYTHON || "python";
const uiSuites = (process.env.UI_TEST_SUITES || "web_patient.tests web_doctor.tests")
  .split(/\s+/)
  .filter(Boolean);
const extraArgs = process.argv.slice(2);
const hasDbFlags = extraArgs.some((arg) => arg === "--keepdb" || arg === "--noinput");
const defaultArgs = hasDbFlags ? [] : ["--keepdb", "--noinput"];
const args = ["manage.py", "test", ...defaultArgs, ...uiSuites, ...extraArgs];

console.log(`[test:ui] Running: ${pythonCmd} ${args.join(" ")}`);

const result = spawnSync(pythonCmd, args, {
  cwd: repoRoot,
  stdio: "inherit",
  shell: process.platform === "win32",
});

if (result.error) {
  console.error(`[test:ui] Failed to run command: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
