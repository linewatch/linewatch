#!/usr/bin/env node
"use strict";

// Thin wrapper around the Linewatch CLI, which is a Python package
// (PyPI `linewatch-cli`). It runs the installed CLI, offers to install it,
// or runs it once with uvx or pipx.

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const PACKAGE = "linewatch-cli";
const SELF = fs.realpathSync(__filename);

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

function candidates(name, env) {
  const exts = process.platform === "win32"
    ? (env.PATHEXT || ".EXE;.CMD;.BAT").split(";")
    : [""];
  const found = [];
  for (const dir of (env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const file = path.join(dir, name + ext);
      if (isExecutable(file)) found.push(file);
    }
  }
  return found;
}

function which(name, env) {
  return candidates(name, env)[0] || null;
}

// The Python CLI is also called `linewatch`: skip this wrapper and the npm
// shims in node_modules/.bin, which point back to it.
function findCli(env) {
  for (const file of candidates("linewatch", env)) {
    let real;
    try {
      real = fs.realpathSync(file);
    } catch {
      continue;
    }
    if (real === SELF) continue;
    if (file.split(path.sep).includes("node_modules")) continue;
    return file;
  }
  return null;
}

// How to run the CLI once without installing it.
function oneOffRunner(env) {
  if (which("uvx", env)) return ["uvx", "--from", PACKAGE, "linewatch"];
  if (which("pipx", env)) return ["pipx", "run", "--spec", PACKAGE, "linewatch"];
  return null;
}

// How to install the CLI for good, and where it puts the command.
function installer(env) {
  if (which("uv", env)) {
    return { command: ["uv", "tool", "install", PACKAGE], binDir: ["uv", "tool", "dir", "--bin"] };
  }
  if (which("pipx", env)) {
    return { command: ["pipx", "install", PACKAGE], binDir: ["pipx", "environment", "--value", "PIPX_BIN_DIR"] };
  }
  return null;
}

function run(command, args) {
  const result = spawnSync(command[0], [...command.slice(1), ...args], { stdio: "inherit" });
  if (result.error) {
    console.error(`linewatch: ${result.error.message}`);
    return 1;
  }
  return result.status === null ? 1 : result.status;
}

function output(command) {
  const result = spawnSync(command[0], command.slice(1), { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

function ask(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
  return new Promise((resolve) => {
    let answered = false;
    rl.question(question, (answer) => {
      answered = true;
      rl.close();
      resolve(!/^n/i.test(answer.trim()));
    });
    // Ctrl-D or a closed stdin counts as no.
    rl.on("close", () => answered || resolve(false));
  });
}

const INSTALL_HELP = `Linewatch runs on Python 3.10 or later. Install it with one of:
  uv tool install ${PACKAGE}
  pipx install ${PACKAGE}
Then run \`linewatch init\` in your repo.`;

async function main(args, env = process.env) {
  const cli = findCli(env);
  if (cli) return run([cli], args);

  const interactive = process.stdin.isTTY && process.stdout.isTTY;
  const fromHook = args[0] === "hook";
  const install = installer(env);

  if (interactive && !fromHook && install) {
    console.error(`Linewatch runs on Python and isn't installed yet.`);
    if (await ask(`Install it now with \`${install.command.join(" ")}\`? [Y/n] `)) {
      const status = run(install.command, []);
      if (status !== 0) return status;
      const binDir = output(install.binDir);
      const installed = findCli(env) || (binDir && findCli({ ...env, PATH: binDir }));
      if (installed) {
        if (binDir && !findCli(env)) {
          console.error(`linewatch: add ${binDir} to your PATH, so git hooks and your shell find it.`);
        }
        return run([installed], args);
      }
      console.error(`linewatch: installed, but the command was not found. ${INSTALL_HELP}`);
      return 1;
    }
  }

  const once = oneOffRunner(env);
  if (once) return run(once, args);

  if (fromHook) {
    console.error("linewatch: not installed, skipping the review.");
    return 0;
  }
  console.error(INSTALL_HELP);
  return 1;
}

if (require.main === module) {
  main(process.argv.slice(2)).then((code) => process.exit(code));
}

module.exports = { findCli, oneOffRunner, installer, main };
