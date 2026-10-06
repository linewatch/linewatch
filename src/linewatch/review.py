"""A review run: the steps in "How a review run works" in the design doc."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from linewatch import gitleaks, llm
from linewatch.config import NO_MODEL, RepoConfig, UserConfig
from linewatch.diff import Changes, FileChange, Hunk, filter_files
from linewatch.findings import SEVERITY_RANK, Finding, blocks

IGNORE_MARKER = "linewatch:ignore"
MAX_CHUNK_LINES = 400
PARALLEL_REQUESTS = 4

# The built-in checks: what to look for and the severities each may report.
CHECKS = {
    "security": {
        "severities": ["critical", "warning", "info"],
        "prompt": (
            "Security: injection (SQL, shell commands, paths, templates), broken "
            "authentication or authorization, secrets or credentials in code, unsafe "
            "deserialization, SSRF, XSS, weak or misused cryptography, and sensitive data "
            "written to logs or responses. critical = exploitable as written; warning = a "
            "risky pattern that needs a closer look; info = a hardening suggestion."
        ),
    },
    "quality": {
        "severities": ["warning", "info"],
        "prompt": (
            "Quality: bugs and logic errors, unhandled errors or edge cases, resource "
            "leaks, race conditions, and code that is misleading or hard to maintain. "
            "warning = likely to cause a bug; info = worth improving. Do not comment on "
            "formatting or naming style."
        ),
    },
}

SYSTEM_PROMPT = """\
You review code changes from a git hook. Find real problems in the changed lines, \
the ones marked with "+". Unchanged lines are context only.

Check for:
{checks}

Rules:
- Report each problem once, on the line in the new file where it is. Use the line \
numbers shown at the start of each line.
- The message says what is wrong and why it matters, in one or two sentences.
- The suggested fix is short: a corrected line or a one-sentence instruction.
- Only report problems you are confident about. If there are none, return an empty list.
"""


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocking: list[Finding] = field(default_factory=list)


def active_checks(repo: RepoConfig) -> dict[str, dict]:
    return {
        name: check for name, check in CHECKS.items()
        if repo.categories.get(name, "off") != "off"
    }


def schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "severity": {"type": "string", "enum": list(SEVERITY_RANK)[::-1]},
                        "category": {"type": "string", "enum": categories},
                        "message": {"type": "string"},
                        "suggested_fix": {"type": "string"},
                    },
                    "required": ["file", "line", "severity", "category", "message", "suggested_fix"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def system_prompt(checks: dict[str, dict]) -> str:
    return SYSTEM_PROMPT.format(checks="\n".join(f"- {c['prompt']}" for c in checks.values()))


def render_file(f: FileChange, hunks=None) -> str:
    """Show a file's diff with new-file line numbers, so the model can cite them."""
    out = [f"File: {f.path}"]
    for hunk in hunks if hunks is not None else f.hunks:
        out.append("...")
        for line in hunk.lines:
            number = "" if line.new_line is None else str(line.new_line)
            out.append(f"{number:>6} {line.tag} {line.text}")
    return "\n".join(out)


def chunks(files: list[FileChange]) -> list[str]:
    """Group the diff into prompts of at most MAX_CHUNK_LINES diff lines.
    Hunks stay whole when they fit in one prompt; longer ones, such as a large
    new file, are cut to fill each prompt."""
    groups: list[list[tuple[FileChange, Hunk]]] = [[]]
    size = 0
    for f in files:
        for hunk in f.hunks:
            lines = hunk.lines
            if size and size + len(lines) > MAX_CHUNK_LINES and len(lines) <= MAX_CHUNK_LINES:
                groups.append([])
                size = 0
            while lines:
                room = MAX_CHUNK_LINES - size
                if room <= 0:
                    groups.append([])
                    size, room = 0, MAX_CHUNK_LINES
                groups[-1].append((f, Hunk(lines[:room])))
                size += len(lines[:room])
                lines = lines[room:]

    prompts = []
    for group in filter(None, groups):
        by_file: dict[str, tuple[FileChange, list[Hunk]]] = {}
        for f, hunk in group:
            by_file.setdefault(f.path, (f, []))[1].append(hunk)
        prompts.append("\n\n".join(render_file(f, hunks) for f, hunks in by_file.values()))
    return prompts


def _normalize_path(path: str) -> str:
    path = path.strip()
    for prefix in ("./", "b/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    return path


def parse_findings(data: dict, checks: dict[str, dict]) -> list[Finding]:
    findings = []
    for item in data.get("findings") or []:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        severity = item.get("severity")
        if category not in checks or severity not in SEVERITY_RANK:
            continue
        allowed = checks[category]["severities"]
        if severity not in allowed:
            severity = allowed[0]  # e.g. a "critical" quality finding becomes a warning
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        message = " ".join(str(item.get("message") or "").split())
        if not message:
            continue
        findings.append(Finding(
            file=_normalize_path(str(item.get("file") or "")),
            line=line,
            severity=severity,
            category=category,
            message=message,
            suggested_fix=str(item.get("suggested_fix") or "").strip(),
        ))
    return findings


class Scope:
    """Which lines findings may point at (step 5) and which are suppressed (step 6)."""

    def __init__(self, changes: Changes, scope: str):
        self.files = {f.path: f for f in changes.files}
        self.read = changes.read
        self.scope = scope
        self._lines: dict[str, list[str]] = {}

    def lines(self, path: str) -> list[str]:
        if path not in self._lines:
            self._lines[path] = (self.read(path) or "").splitlines()
        return self._lines[path]

    def contains(self, f: Finding) -> bool:
        change = self.files.get(f.file)
        if change is None:
            return False
        if self.scope == "changed-files":
            return 1 <= f.line <= len(self.lines(f.file))
        return f.line in change.added_lines

    def suppressed(self, f: Finding) -> bool:
        lines = self.lines(f.file)
        return 1 <= f.line <= len(lines) and IGNORE_MARKER in lines[f.line - 1]


def run(
    changes: Changes,
    repo: RepoConfig,
    user: UserConfig | None,
    complete: Callable[..., dict] = llm.complete,
) -> Result:
    result = Result()

    # Step 2: excluded files and the size limit.
    changes = filter_files(changes, repo.exclude)
    if changes.skipped:
        result.notes.append(f"Skipped {len(changes.skipped)} file(s): {', '.join(changes.skipped)}")
    if not changes.files:
        return result
    use_model = user is not None and user.provider != NO_MODEL
    if user is None:
        result.notes.append("No model set up: run `linewatch init`. Running the deterministic checks only.")
    size = sum(f.changed_count for f in changes.files)
    if use_model and size > repo.max_diff_lines:
        use_model = False
        result.notes.append(
            f"The diff has {size} changed lines, over the limit of {repo.max_diff_lines}: "
            "running the deterministic checks only."
        )

    scope = Scope(changes, repo.scope)
    found: list[Finding] = []

    # Step 3: deterministic checks first.
    if repo.categories.get("security", "off") != "off":
        if gitleaks.available():
            try:
                found += gitleaks.scan(changes)
            except gitleaks.GitleaksError as exc:
                result.notes.append(f"gitleaks failed, secrets were not scanned: {exc}")
        else:
            result.notes.append("gitleaks is not installed, so secrets were not scanned.")

    # Step 4: the model, one request per chunk.
    checks = active_checks(repo)
    if use_model and checks:
        found += _ask_model(changes, checks, user, complete, result)

    # Steps 5 and 6: keep findings on real lines in scope, drop suppressed ones.
    seen = set()
    for f in found:
        if f.key in seen or not scope.contains(f) or scope.suppressed(f):
            continue
        seen.add(f.key)
        result.findings.append(f)
    result.findings.sort(key=lambda f: (f.file, f.line, -SEVERITY_RANK[f.severity]))

    # Step 8: the blocking levels.
    result.blocking = [f for f in result.findings if blocks(f, repo.categories.get(f.category))]
    return result


def _ask_model(changes, checks, user, complete, result) -> list[Finding]:
    system = system_prompt(checks)
    answer_schema = schema(list(checks))
    pieces = chunks(changes.files)

    def ask(prompt):
        return parse_findings(complete(user, system, prompt, answer_schema), checks)

    found, errors = [], []
    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        futures = [pool.submit(ask, piece) for piece in pieces]
        for future in futures:
            try:
                found += future.result()
            except llm.ModelError as exc:
                errors.append(str(exc))
    if errors:
        # Step 9: fail open. One line, and the deterministic findings still count.
        failed = f"{len(errors)} of {len(pieces)} part(s)" if len(pieces) > 1 else "the review"
        result.notes.append(f"The model failed for {failed}, so it was skipped: {errors[0]}")
    return found
