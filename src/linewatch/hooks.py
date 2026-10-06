"""Install the git hooks that run Linewatch.

Linewatch wires both the pre-commit and the pre-push hook. Each run of
`linewatch hook <name>` checks the effective hook setting (the dev's local
override, or the team default in `.linewatch.yaml`) and exits at once if that
hook is not active. That way a change of either setting takes effect without
reinstalling, and the committed Husky and pre-commit framework files work for
every dev on the team.
"""

from __future__ import annotations

import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from linewatch.config import (
    REPO_CONFIG_NAME,
    ConfigError,
    effective_hook,
    hook_is_active,
    load_repo_config,
    load_user_config,
)

GIT_HOOKS = ("pre-commit", "pre-push")
MANAGERS = ("native", "husky", "pre-commit")

MARKER = "linewatch-managed"
BACKUP_SUFFIX = ".pre-linewatch"
PRE_COMMIT_CONFIG = ".pre-commit-config.yaml"

NATIVE_TEMPLATE = """\
#!/bin/sh
# {marker}: installed by `linewatch init`.
# Bypass once with `git commit --no-verify` or `git push --no-verify`.
# A hook that was here before is kept as {hook}{backup} and runs first.
hook_dir=$(dirname "$0")
{read_stdin}
feed() {{ if [ -n "$input" ]; then printf '%s\\n' "$input"; fi; }}

if [ -x "$hook_dir/{hook}{backup}" ]; then
  feed | "$hook_dir/{hook}{backup}" "$@" || exit $?
fi

if [ -x {python} ]; then
  feed | {python} -m linewatch hook {hook} "$@"
  exit $?
elif command -v linewatch >/dev/null 2>&1; then
  feed | linewatch hook {hook} "$@"
  exit $?
fi
echo "linewatch: not installed, skipping the review." >&2
exit 0
"""

HUSKY_LINES = """\
# {marker}: AI code review. Skipped when linewatch is not installed.
if command -v linewatch >/dev/null 2>&1; then linewatch hook {hook} "$@" || exit $?; fi
"""

PRE_COMMIT_ENTRY = (
    "sh -c 'command -v linewatch >/dev/null 2>&1 || exit 0; "
    "exec linewatch hook {hook}'"
)


class HookError(Exception):
    """Raised when the hooks cannot be installed."""


@dataclass
class InstallResult:
    manager: str
    changed: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HookError(f"git {' '.join(args)} failed: {exc}")
    return out.stdout.strip()


def git_hooks_dir(root: Path) -> Path:
    """The directory git runs hooks from. Honours core.hooksPath and worktrees."""
    return (root / _git(root, "rev-parse", "--git-path", "hooks")).resolve()


def detect_manager(root: Path) -> str:
    hooks_path = _git_config(root, "core.hooksPath")
    if hooks_path:
        resolved = (root / hooks_path).resolve()
        husky = (root / ".husky").resolve()
        if resolved == husky or husky in resolved.parents:
            return "husky"
        return "native"
    if (root / PRE_COMMIT_CONFIG).exists():
        return "pre-commit"
    if (root / ".husky").is_dir():
        return "husky"
    return "native"


def _git_config(root: Path, key: str) -> str | None:
    out = subprocess.run(
        ["git", "config", "--get", key], cwd=root, capture_output=True, text=True
    )
    return out.stdout.strip() or None


def install(root: Path, manager: str | None = None) -> InstallResult:
    manager = manager or detect_manager(root)
    if manager == "native":
        return install_native(root)
    if manager == "husky":
        return install_husky(root)
    if manager == "pre-commit":
        return install_pre_commit(root)
    raise HookError(f"unknown hook manager {manager!r}")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def native_script(hook: str, python: str = sys.executable) -> str:
    return NATIVE_TEMPLATE.format(
        marker=MARKER,
        hook=hook,
        backup=BACKUP_SUFFIX,
        python=shlex.quote(python),
        # pre-push gets the refs on stdin; keep them for both hooks that run.
        read_stdin="input=$(cat)" if hook == "pre-push" else "input=",
    )


def install_native(root: Path) -> InstallResult:
    result = InstallResult("native")
    hooks_dir = git_hooks_dir(root)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for hook in GIT_HOOKS:
        path = hooks_dir / hook
        if path.exists() and MARKER not in path.read_text(errors="replace"):
            backup = path.with_name(hook + BACKUP_SUFFIX)
            if backup.exists():
                raise HookError(
                    f"{path} is not a Linewatch hook and {backup.name} already exists. "
                    "Merge them by hand, then run `linewatch init` again."
                )
            path.rename(backup)
            result.notes.append(f"Kept your existing {hook} hook as {backup.name}; it still runs first.")
        path.write_text(native_script(hook))
        _make_executable(path)
        result.changed.append(path)
    return result


def install_husky(root: Path) -> InstallResult:
    result = InstallResult("husky")
    husky_dir = root / ".husky"
    husky_dir.mkdir(exist_ok=True)
    # Husky 8 runs the files directly and needs a shebang; Husky 9 doesn't.
    husky8 = (husky_dir / "_" / "husky.sh").exists()
    for hook in GIT_HOOKS:
        path = husky_dir / hook
        text = path.read_text() if path.exists() else ""
        if MARKER in text:
            continue
        if not text and husky8:
            text = '#!/usr/bin/env sh\n. "$(dirname -- "$0")/_/husky.sh"\n'
        if text and not text.endswith("\n"):
            text += "\n"
        if text:
            text += "\n"
        path.write_text(text + HUSKY_LINES.format(marker=MARKER, hook=hook))
        _make_executable(path)
        result.changed.append(path)
    if result.changed:
        result.notes.append("Commit the changed .husky files so the team gets the hooks.")
    if not _git_config(root, "core.hooksPath"):
        result.notes.append("Husky is not active in this clone yet. Run `npm install` to activate it.")
    return result


def pre_commit_hooks() -> list[dict]:
    return [
        {
            "id": f"linewatch-{hook}",
            "name": f"linewatch ({hook})",
            "entry": PRE_COMMIT_ENTRY.format(hook=hook),
            "language": "system",
            "pass_filenames": False,
            "always_run": True,
            "verbose": True,
            "stages": [hook],
        }
        for hook in GIT_HOOKS
    ]


def pre_commit_snippet(indent: str = "  ") -> str:
    block = yaml.safe_dump(
        [{"repo": "local", "hooks": pre_commit_hooks()}], sort_keys=False, width=200
    )
    return "".join(indent + line + "\n" for line in block.splitlines())


def _has_linewatch_hooks(data) -> bool:
    if not isinstance(data, dict):
        return False
    for repo in data.get("repos") or []:
        for hook in (repo or {}).get("hooks") or []:
            if str((hook or {}).get("id", "")).startswith("linewatch"):
                return True
    return False


def add_to_pre_commit_config(text: str) -> str | None:
    """Return the config with the Linewatch hooks appended, or None if it
    can't be done without rewriting the file (which would lose its comments)."""
    top_level = [
        m for m in re.finditer(r"^([A-Za-z_][\w-]*)\s*:", text, re.MULTILINE)
    ]
    if not top_level or top_level[-1].group(1) != "repos":
        return None
    after = text[top_level[-1].end():]
    item = re.search(r"^([ \t]*)- ", after, re.MULTILINE)
    indent = item.group(1) if item else "  "
    if after.strip() in ("", "[]"):
        text = text[: top_level[-1].end()]
        indent = "  "
    if not text.endswith("\n"):
        text += "\n"
    new_text = text + pre_commit_snippet(indent)
    try:
        if not _has_linewatch_hooks(yaml.safe_load(new_text)):
            return None
    except yaml.YAMLError:
        return None
    return new_text


def run_hook(
    hook: str,
    args: list[str] | None = None,
    cwd: Path | None = None,
    user_config_file: Path | None = None,
    stdin: str | None = None,
) -> int:
    """Entry point git calls through `linewatch hook <name>`. Never asks anything
    (use case 14: commits from a GUI client have no terminal)."""
    from linewatch import run

    try:
        root = Path(_git(cwd or Path.cwd(), "rev-parse", "--show-toplevel"))
        if not (root / REPO_CONFIG_NAME).exists():
            return 0
        repo = load_repo_config(root)
        try:
            user = load_user_config(user_config_file)
        except ConfigError:
            user = None  # the review reports it and runs the deterministic checks
        setting = effective_hook(repo, user)
    except (HookError, ConfigError) as exc:
        # Fail open: a broken setup never blocks a commit or push.
        print(f"linewatch: skipping the review: {exc}", file=sys.stderr)
        return 0

    if not hook_is_active(hook, setting):
        return 0
    if stdin is None:
        stdin = sys.stdin.read() if hook == "pre-push" and not sys.stdin.isatty() else ""
    return run.run_hook(root, hook, repo, stdin, args or [], user_config_file)


def install_pre_commit(root: Path) -> InstallResult:
    result = InstallResult("pre-commit")
    path = root / PRE_COMMIT_CONFIG
    text = path.read_text() if path.exists() else "repos:\n"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HookError(f"{path} is not valid YAML: {exc}")

    if not _has_linewatch_hooks(data):
        new_text = add_to_pre_commit_config(text)
        if new_text is None:
            raise HookError(
                f"Could not add Linewatch to {path} without rewriting it. "
                f"Add this under `repos:` by hand, then run `linewatch init` again:\n\n"
                + pre_commit_snippet()
            )
        path.write_text(new_text)
        result.changed.append(path)
        result.notes.append(f"Commit {PRE_COMMIT_CONFIG} so the team gets the hooks.")

    hook_types = [arg for hook in GIT_HOOKS for arg in ("--hook-type", hook)]
    command = ["pre-commit", "install", *hook_types]
    if shutil.which("pre-commit") is None:
        result.notes.append(
            "pre-commit is not installed. Install it, then run: " + " ".join(command)
        )
        return result
    out = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        raise HookError(f"`{' '.join(command)}` failed:\n{out.stdout}{out.stderr}")
    return result
