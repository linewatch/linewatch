"""The finding type shared by the checks, the review and the output."""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


@dataclass
class Finding:
    file: str
    line: int
    severity: str  # critical | warning | info
    category: str
    message: str
    suggested_fix: str = ""
    source: str = "model"  # "model" or the deterministic tool, e.g. "gitleaks"

    @property
    def key(self) -> tuple:
        return (self.file, self.line, self.category, self.message)


def blocks(finding: Finding, setting: str | None) -> bool:
    """True if the finding reaches its category's `block_at` level."""
    if setting not in SEVERITY_RANK:
        return False  # never, off, or a category without a setting
    return SEVERITY_RANK[finding.severity] >= SEVERITY_RANK[setting]
