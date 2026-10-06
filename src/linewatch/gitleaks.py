"""Secret scanning with gitleaks, run before anything is sent to a model."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from linewatch.diff import Changes
from linewatch.findings import Finding

TIMEOUT = 120


class GitleaksError(Exception):
    pass


def available() -> bool:
    return shutil.which("gitleaks") is not None


def scan(changes: Changes) -> list[Finding]:
    """Scan the new version of each changed file. Returns findings on any line;
    the review keeps the ones in scope."""
    with tempfile.TemporaryDirectory(prefix="linewatch-") as tmp:
        src = Path(tmp).resolve() / "src"
        for f in changes.files:
            content = changes.read(f.path)
            if content is None:
                continue
            target = src / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        if not src.exists():
            return []
        report = Path(tmp) / "report.json"
        _run(src, report)
        try:
            data = json.loads(report.read_text() or "[]")
        except (OSError, ValueError) as exc:
            raise GitleaksError(f"unreadable gitleaks report: {exc}")

    findings = []
    for leak in data or []:
        path = Path(leak.get("File", ""))
        if not path.is_absolute():
            path = src / path
        try:
            rel = path.resolve().relative_to(src).as_posix()
        except ValueError:
            rel = path.as_posix()
        rule = leak.get("RuleID", "secret")
        description = leak.get("Description") or "possible secret"
        findings.append(Finding(
            file=rel,
            line=int(leak.get("StartLine") or 1),
            severity="critical",
            category="security",
            # Never repeat the secret itself in the output.
            message=f"Possible secret ({rule}): {description}",
            suggested_fix="Remove the secret, rotate it, and load it from the environment or a secret store.",
            source="gitleaks",
        ))
    return findings


def _run(src: Path, report: Path) -> None:
    common = ["--report-format", "json", "--report-path", str(report),
              "--no-banner", "--exit-code", "0"]
    # gitleaks 8.19+ has `dir`; older versions use `detect --no-git`.
    attempts = [
        ["gitleaks", "dir", str(src), *common],
        ["gitleaks", "detect", "--no-git", "--source", str(src), *common],
    ]
    errors = []
    for command in attempts:
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitleaksError(str(exc))
        if out.returncode == 0:
            return
        errors.append(out.stderr.strip())
    raise GitleaksError(errors[-1] or "gitleaks failed")
