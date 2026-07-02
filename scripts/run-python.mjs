#!/usr/bin/env node
// Resolve a working Python 3 (py -3 / python3 / python) and forward all args.
// npm guarantees Node, so this shim gives npm scripts a cross-platform Python entry.
import { spawnSync } from "node:child_process";

const candidates = [
  ["py", ["-3"]],
  ["python3", []],
  ["python", []],
];

function isPython3(command, baseArgs) {
  const probe = spawnSync(command, [...baseArgs, "--version"], { encoding: "utf8" });
  if (probe.error || probe.status !== 0) return false;
  return /Python 3\./.test(`${probe.stdout}${probe.stderr}`);
}

const resolved = candidates.find(([command, baseArgs]) => isPython3(command, baseArgs));
if (!resolved) {
  console.error("Python 3 not found. Install Python 3 or ensure py -3, python3, or python points to Python 3.");
  process.exit(1);
}

const [command, baseArgs] = resolved;
const result = spawnSync(command, [...baseArgs, ...process.argv.slice(2)], { stdio: "inherit" });
process.exit(result.status ?? 1);
