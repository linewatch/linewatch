"use strict";

// Turns .linewatch/last.sarif into plain finding objects. No vscode import,
// so it runs under `node --test`.

const SEVERITY_FROM_LEVEL = { error: "critical", warning: "warning", note: "info" };

function parseFindings(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return null; // half-written or broken file: keep the current markers
  }
  const findings = [];
  for (const run of (data && data.runs) || []) {
    for (const result of run.results || []) {
      const location = result.locations && result.locations[0];
      const physical = location && location.physicalLocation;
      const uri = physical && physical.artifactLocation && physical.artifactLocation.uri;
      const line = physical && physical.region && physical.region.startLine;
      if (!uri || !Number.isInteger(line) || line < 1) continue;
      const props = result.properties || {};
      findings.push({
        file: uri,
        line,
        severity: props.severity || SEVERITY_FROM_LEVEL[result.level] || "warning",
        category: props.category || result.ruleId || "linewatch",
        message: (result.message && result.message.text) || "",
        suggestedFix: props.suggestedFix || "",
      });
    }
  }
  return findings;
}

function diagnosticMessage(finding) {
  return finding.suggestedFix
    ? `${finding.message}\nFix: ${finding.suggestedFix}`
    : finding.message;
}

module.exports = { parseFindings, diagnosticMessage };
