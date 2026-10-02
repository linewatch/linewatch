"""Whole review runs: from git, through the hooks, to the exit code and SARIF file."""

import json
import os
import subprocess

import pytest
from conftest import commit_all, fake_tool, git, write

from linewatch import hooks, run
from linewatch.config import RepoConfig, UserConfig, write_repo_config, write_user_config

LEAK_ON_LINE_2 = """\
while [ $# -gt 0 ]; do
  case "$1" in dir) src="$2"; shift;; --report-path) report="$2"; shift;; esac
  shift
done
echo "[{\\"File\\": \\"$src/app.py\\", \\"StartLine\\": 2, \\"RuleID\\": \\"aws-key\\", \\"Description\\": \\"AWS key\\"}]" > "$report"
"""


@pytest.fixture
def repo(make_repo, isolated, monkeypatch):
    root = make_repo()
    write(root, "app.py", "x = 1\n")
    commit_all(root, "first")
    user_file = isolated / "xdg" / "linewatch" / "config.yaml"
    write_user_config(UserConfig(provider="none"), user_file)
    return root


@pytest.fixture
def leaky_gitleaks(isolated, monkeypatch):
    bin_dir = isolated / "bin"
    fake_tool(bin_dir, "gitleaks", LEAK_ON_LINE_2)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def sarif_results(root):
    return json.loads((root / ".linewatch" / "last.sarif").read_text())["runs"][0]["results"]


def test_commit_is_blocked_by_a_secret(repo, leaky_gitleaks):
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    hooks.install(repo)
    write(repo, "app.py", "x = 1\nkey = 'AKIA...'\n")
    git(repo, "add", "app.py")
    out = git(repo, "commit", "-q", "-m", "leak", check=False)
    assert out.returncode != 0
    # git sends hook output to stderr.
    finding = "app.py:2:1: critical: [security] Possible secret (aws-key): AWS key (blocks)"
    assert finding in out.stderr
    assert out.stderr.index(finding) < out.stderr.index("block this commit")
    assert sarif_results(repo)[0]["locations"][0]["physicalLocation"]["region"]["startLine"] == 2
    # --no-verify is the emergency bypass.
    assert git(repo, "commit", "-q", "--no-verify", "-m", "leak", check=False).returncode == 0


def test_push_is_blocked_by_a_secret(repo, leaky_gitleaks, isolated):
    write_repo_config(RepoConfig(hook="pre-push"), repo)
    hooks.install(repo)
    remote = isolated / "remote.git"
    git(isolated, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "--no-verify", "origin", "main")

    write(repo, "app.py", "x = 1\nkey = 'AKIA...'\n")
    commit_all(repo, "leak")
    out = git(repo, "push", "-q", "origin", "main", check=False)
    assert out.returncode != 0
    assert "block this push" in out.stderr


def test_a_secret_on_an_unchanged_line_does_not_block(repo, leaky_gitleaks):
    write(repo, "app.py", "x = 1\nkey = 'old'\n")
    commit_all(repo, "old secret")
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    hooks.install(repo)
    write(repo, "app.py", "y = 0\nkey = 'old'\n")  # only line 1 changes
    git(repo, "add", "app.py")
    assert git(repo, "commit", "-q", "-m", "ok", check=False).returncode == 0


def test_review_changes_with_a_model(repo):
    write(repo, "app.py", "x = 1\neval(input())\n")
    from linewatch import diff

    def complete(user, system, prompt, schema):
        return {"findings": [{"file": "app.py", "line": 2, "severity": "warning", "category": "quality",
                              "message": "eval of user input", "suggested_fix": ""}]}

    write_user_config(UserConfig(provider="ollama", model="m", base_url="http://x"),
                      repo.parent / "xdg" / "linewatch" / "config.yaml")
    code = run.review_changes(repo, [diff.uncommitted(repo)], RepoConfig(), complete=complete)
    assert code == 0  # quality blocks at `never`
    assert sarif_results(repo)[0]["level"] == "warning"


def test_manual_review(repo, capsys, no_gitleaks):
    write(repo, "app.py", "x = 2\n")
    assert run.run_manual(None, cwd=repo) == 0
    err = capsys.readouterr().err
    assert "no .linewatch.yaml here" in err
    assert "reviewing the uncommitted changes" in err


def test_manual_review_nothing_to_do(repo, capsys):
    assert run.run_manual(None, cwd=repo) == 0
    assert "nothing to review" in capsys.readouterr().err


def test_manual_review_bad_range(repo, capsys):
    assert run.run_manual("nope..HEAD", cwd=repo) == 2
    assert "unknown commit" in capsys.readouterr().err


def test_manual_review_blocks_with_exit_code_1(repo, leaky_gitleaks):
    write(repo, "app.py", "x = 1\nkey = 'AKIA...'\n")
    assert run.run_manual(None, cwd=repo) == 1


def test_pre_commit_framework_push_range_from_env(repo, monkeypatch):
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    write(repo, "app.py", "x = 1\ny = 2\n")
    head = commit_all(repo)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head)
    (changes,) = run.hook_changes(repo, "pre-push", "", [])
    assert changes.files[0].added_lines == {2}


def test_cli_review_command(repo):
    env = dict(os.environ)
    out = subprocess.run([os.sys.executable, "-m", "linewatch", "review", "--range", "HEAD"],
                         cwd=repo, capture_output=True, text=True, env=env)
    assert out.returncode == 0
    assert "nothing to review" in out.stderr
