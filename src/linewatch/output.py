"""Terminal output and the SARIF file the IDE reads."""

from __future__ import annotations

import json
from pathlib import Path

from linewatch import __version__
from linewatch.findings import Finding

SARIF_PATH = Path(".linewatch") / "last.sarif"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_LEVEL = {"critical": "error", "warning": "warning", "info": "note"}


def terminal_lines(findings: list[Finding], blocking: list[Finding]) -> list[str]:
    """`file:line:col: severity: message`, which IDE problem panels can read."""
    blocking_keys = {f.key for f in blocking}
    lines = []
    for f in findings:
        mark = " (blocks)" if f.key in blocking_keys else ""
        lines.append(f"{f.file}:{f.line}:1: {f.severity}: [{f.category}] {f.message}{mark}")
        if f.suggested_fix:
            fix = " ".join(f.suggested_fix.splitlines()).strip()
            lines.append(f"    fix: {fix}")
    return lines


def sarif(findings: list[Finding]) -> dict:
    categories = sorted({f.category for f in findings})
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "linewatch",
                "version": __version__,
                "informationUri": "https://github.com/linewatch/linewatch",
                "rules": [{"id": c, "name": c} for c in categories],
            }},
            "results": [
                {
                    "ruleId": f.category,
                    "level": SARIF_LEVEL[f.severity],
                    "message": {"text": f.message},
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": f.file, "uriBaseId": "%SRCROOT%"},
                        "region": {"startLine": f.line},
                    }}],
                    "properties": {
                        "severity": f.severity,
                        "category": f.category,
                        "source": f.source,
                        "suggestedFix": f.suggested_fix,
                    },
                }
                for f in findings
            ],
        }],
    }


def write_sarif(root: Path, findings: list[Finding]) -> Path:
    """Write the findings for the IDE. An empty run clears the old markers."""
    folder = root / SARIF_PATH.parent
    folder.mkdir(exist_ok=True)
    # last.sarif changes on every run; checks and the baseline in this folder are committed.
    ignore = folder / ".gitignore"
    entries = ignore.read_text().splitlines() if ignore.exists() else []
    if SARIF_PATH.name not in entries:
        ignore.write_text("\n".join(entries + [SARIF_PATH.name]) + "\n")
    path = root / SARIF_PATH
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sarif(findings), indent=2) + "\n")
    tmp.replace(path)  # the IDE never sees a half-written file
    return path
