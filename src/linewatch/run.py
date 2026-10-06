"""Run a review from a hook or by hand, print it and decide the exit code."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from linewatch import diff, llm, output, review
from linewatch.config import (
    REPO_CONFIG_NAME,
    ConfigError,
    RepoConfig,
    load_repo_config,
    load_user_config,
)
from linewatch.diff import Changes, GitError
from linewatch.findings import Finding


def say(message: str) -> None:
    print(f"linewatch: {message}", file=sys.stderr)


def review_changes(
    root: Path,
    change_sets: list[Changes],
    repo: RepoConfig,
    user_config_file: Path | None = None,
    action: str | None = None,
    complete: Callable[..., dict] = llm.complete,
) -> int:
    """Review, print, write the SARIF file. Returns 1 if a finding blocks."""
    try:
        user = load_user_config(user_config_file)
    except ConfigError as exc:
        say(f"{exc}; running the deterministic checks only.")
        user = None

    findings: list[Finding] = []
    blocking: list[Finding] = []
    for changes in change_sets:
        if len(change_sets) > 1:
            say(f"reviewing {changes.description}")
        result = review.run(changes, repo, user, complete)
        for note in result.notes:
            say(note)
        findings += result.findings
        blocking += result.blocking

    for line in output.terminal_lines(findings, blocking):
        print(line)
    sys.stdout.flush()  # git merges hook stdout into stderr; keep the summary last
    try:
        output.write_sarif(root, findings)
    except OSError as exc:
        say(f"could not write {output.SARIF_PATH}: {exc}")

    if not findings:
        say("no findings.")
    if blocking:
        what = f"this {action}" if action else "these changes"
        say(
            f"{len(blocking)} finding(s) block {what}. Fix them, add `{review.IGNORE_MARKER}` "
            "on the line, or bypass with --no-verify."
        )
        return 1
    if findings:
        say(f"{len(findings)} finding(s), none blocking.")
    return 0


def hook_changes(root: Path, hook: str, stdin: str, args: list[str]) -> list[Changes]:
    if hook == "pre-commit":
        return [diff.staged(root)]
    # pre-push: git passes the remote name and the refs on stdin. The
    # pre-commit framework passes the range in environment variables instead.
    remote = args[0] if args else os.environ.get("PRE_COMMIT_REMOTE_NAME", "origin")
    if not stdin.strip():
        from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
        to_ref = os.environ.get("PRE_COMMIT_TO_REF")
        if from_ref and to_ref:
            return [diff.commit_range(root, from_ref, to_ref, "commits being pushed")]
    return diff.pushed(root, stdin, remote)


def run_hook(root: Path, hook: str, repo: RepoConfig, stdin: str, args: list[str],
             user_config_file: Path | None = None) -> int:
    try:
        change_sets = hook_changes(root, hook, stdin, args)
    except GitError as exc:
        say(f"skipping the review: {exc}")
        return 0
    action = "commit" if hook == "pre-commit" else "push"
    return review_changes(root, change_sets, repo, user_config_file, action)


def run_manual(range_spec: str | None, cwd: Path | None = None,
               user_config_file: Path | None = None) -> int:
    """`linewatch review` (use case 10)."""
    try:
        root = Path(diff.git(cwd or Path.cwd(), "rev-parse", "--show-toplevel").strip())
        changes = diff.parse_range(root, range_spec) if range_spec else diff.uncommitted(root)
    except GitError as exc:
        say(str(exc))
        return 2
    repo = RepoConfig()
    if (root / REPO_CONFIG_NAME).exists():
        try:
            repo = load_repo_config(root)
        except ConfigError as exc:
            say(str(exc))
            return 2
    else:
        say(f"no {REPO_CONFIG_NAME} here, using the default rules. Run `linewatch init` to set them.")
    if not any(f.hunks for f in changes.files):
        say(f"nothing to review in the {changes.description}.")
        return 0
    say(f"reviewing the {changes.description}...")
    return review_changes(root, [changes], repo, user_config_file)
