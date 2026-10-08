"use strict";

const assert = require("node:assert");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const WRAPPER = path.join(__dirname, "..", "bin", "linewatch.js");

function tool(dir, name, script) {
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  fs.writeFileSync(file, `#!/bin/sh\n${script}`);
  fs.chmodSync(file, 0o755);
  return file;
}

// Run the wrapper without a terminal, like a git hook does.
function wrapper(args, PATH, input = "") {
  return spawnSync(process.execPath, [WRAPPER, ...args], {
    env: { PATH, HOME: os.tmpdir() },
    input,
    encoding: "utf8",
  });
}

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "linewatch-npm-"));
}

// Fake Python CLI: print the arguments and stdin, exit with 3.
const FAKE_CLI = 'echo "cli $*"; cat; exit 3\n';

test("runs the installed CLI with the arguments, stdin and exit code", () => {
  const bin = path.join(tmp(), "bin");
  tool(bin, "linewatch", FAKE_CLI);
  const result = wrapper(["hook", "pre-push", "origin"], `${bin}:/usr/bin:/bin`, "refs\n");
  assert.strictEqual(result.stdout, "cli hook pre-push origin\nrefs\n");
  assert.strictEqual(result.status, 3);
});

test("skips itself and the npm shims in node_modules", () => {
  const root = tmp();
  const shims = path.join(root, "node_modules", ".bin");
  fs.mkdirSync(shims, { recursive: true });
  fs.symlinkSync(WRAPPER, path.join(shims, "linewatch"));
  const bin = path.join(root, "bin");
  tool(bin, "linewatch", FAKE_CLI);
  const result = wrapper(["review"], `${shims}:${bin}:/usr/bin:/bin`);
  assert.strictEqual(result.stdout, "cli review\n");
});

test("runs the CLI once with uvx when it isn't installed", () => {
  const bin = path.join(tmp(), "bin");
  tool(bin, "uvx", 'echo "uvx $*"\n');
  const result = wrapper(["review"], `${bin}:/usr/bin:/bin`);
  assert.strictEqual(result.stdout, "uvx --from linewatch-cli linewatch review\n");
  assert.strictEqual(result.status, 0);
});

test("falls back to pipx run", () => {
  const bin = path.join(tmp(), "bin");
  tool(bin, "pipx", 'echo "pipx $*"\n');
  const result = wrapper(["init", "--yes"], `${bin}:/usr/bin:/bin`);
  assert.strictEqual(result.stdout, "pipx run --spec linewatch-cli linewatch init --yes\n");
});

test("a hook without the CLI, uvx or pipx skips the review", () => {
  const result = wrapper(["hook", "pre-commit"], `${tmp()}:/usr/bin:/bin`);
  assert.strictEqual(result.status, 0);
  assert.match(result.stderr, /not installed, skipping the review/);
});

test("a command without the CLI, uvx or pipx explains how to install it", () => {
  const result = wrapper(["init"], `${tmp()}:/usr/bin:/bin`);
  assert.strictEqual(result.status, 1);
  assert.match(result.stderr, /uv tool install linewatch-cli/);
  assert.match(result.stderr, /pipx install linewatch-cli/);
});
