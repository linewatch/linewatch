"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { parseFindings, diagnosticMessage } = require("../sarif");

function result(overrides = {}) {
  return {
    ruleId: "security",
    level: "error",
    message: { text: "SQL injection" },
    locations: [{ physicalLocation: {
      artifactLocation: { uri: "src/app.py", uriBaseId: "%SRCROOT%" },
      region: { startLine: 42 },
    } }],
    properties: { severity: "critical", category: "security", suggestedFix: "Use a parameterized query." },
    ...overrides,
  };
}

const sarif = (results) => JSON.stringify({ version: "2.1.0", runs: [{ results }] });

test("reads findings written by the Python CLI", () => {
  assert.deepStrictEqual(parseFindings(sarif([result()])), [{
    file: "src/app.py",
    line: 42,
    severity: "critical",
    category: "security",
    message: "SQL injection",
    suggestedFix: "Use a parameterized query.",
  }]);
});

test("falls back to the SARIF level without Linewatch properties", () => {
  const [finding] = parseFindings(sarif([result({ level: "note", properties: undefined })]));
  assert.strictEqual(finding.severity, "info");
  assert.strictEqual(finding.category, "security");
});

test("skips results without a usable location", () => {
  const noLine = result();
  noLine.locations[0].physicalLocation.region = {};
  assert.deepStrictEqual(parseFindings(sarif([noLine, result({ locations: [] })])), []);
});

test("an empty run clears the findings", () => {
  assert.deepStrictEqual(parseFindings(sarif([])), []);
});

test("a broken file returns null so the markers stay", () => {
  assert.strictEqual(parseFindings('{"runs": ['), null);
});

test("the message carries the suggested fix", () => {
  assert.strictEqual(
    diagnosticMessage({ message: "SQL injection", suggestedFix: "Use ?" }),
    "SQL injection\nFix: Use ?"
  );
  assert.strictEqual(diagnosticMessage({ message: "Unused", suggestedFix: "" }), "Unused");
});
