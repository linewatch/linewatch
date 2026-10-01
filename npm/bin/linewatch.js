#!/usr/bin/env node
"use strict";

const { version } = require("../package.json");

if (process.argv.includes("--version") || process.argv.includes("-V")) {
  console.log(`linewatch ${version}`);
} else {
  console.log(
    `linewatch ${version}: early placeholder release. ` +
      "The review engine is under development."
  );
}
