import os
import subprocess
from pathlib import Path

import pytest
import yaml

from linewatch import hooks
from linewatch.config import RepoConfig, UserConfig, write_repo_config, write_user_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Keep the real user config out of the tests, also for hooks git runs."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    return dict(os.environ)


@pytest.fixture
def repo(tmp_path, env):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "config", "user.name", "Dev")
    git(root, "config", "commit.gpgsign", "false")
    return root


def git(root, *args, check=True):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check)


def commit(root, name="file.txt"):
    (root / name).write_text(name)
    git(root, "add", name)
    return git(root, "commit", "-q", "-m", f"add {name}", check=False)


def user_config(hook=None):
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "linewatch" / "config.yaml"
    write_user_config(UserConfig(provider="none", hook=hook), path)


# Detection

def test_detect_native(repo):
    assert hooks.detect_manager(repo) == "native"


def test_detect_pre_commit_framework(repo):
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n")
    assert hooks.detect_manager(repo) == "pre-commit"


def test_detect_husky_by_folder_or_hooks_path(repo):
    (repo / ".husky").mkdir()
    assert hooks.detect_manager(repo) == "husky"
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n")
    git(repo, "config", "core.hooksPath", ".husky/_")
    assert hooks.detect_manager(repo) == "husky"


def test_detect_custom_hooks_path_is_native(repo):
    git(repo, "config", "core.hooksPath", "githooks")
    assert hooks.detect_manager(repo) == "native"
    assert hooks.git_hooks_dir(repo) == (repo / "githooks").resolve()


# Native hooks, run by real git

def test_native_hook_runs_on_commit(repo):
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    result = hooks.install(repo)
    assert result.manager == "native"
    out = commit(repo)
    assert out.returncode == 0
    assert "linewatch: no findings." in out.stderr


def test_native_hook_stays_quiet_when_hook_not_active(repo):
    write_repo_config(RepoConfig(hook="pre-push"), repo)
    hooks.install(repo)
    out = commit(repo)
    assert out.returncode == 0
    assert "linewatch" not in out.stderr


def test_local_override_wins_without_reinstalling(repo):
    write_repo_config(RepoConfig(hook="pre-push"), repo)
    hooks.install(repo)
    user_config(hook="both")
    assert "linewatch: no findings." in commit(repo).stderr


def test_no_verify_bypasses(repo):
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    hooks.install(repo)
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    out = git(repo, "commit", "-q", "--no-verify", "-m", "a")
    assert "linewatch" not in out.stderr


def test_broken_team_config_fails_open(repo):
    (repo / ".linewatch.yaml").write_text("hook: sometimes\n")
    hooks.install(repo)
    out = commit(repo)
    assert out.returncode == 0
    assert "skipping the review" in out.stderr


def test_existing_hook_is_kept_and_runs_first(repo, tmp_path):
    write_repo_config(RepoConfig(hook="pre-push"), repo)
    hooks_dir = repo / ".git" / "hooks"
    log = tmp_path / "legacy.log"
    legacy = hooks_dir / "pre-push"
    legacy.write_text(f'#!/bin/sh\necho "args: $*" > {log}\ncat >> {log}\n')
    legacy.chmod(0o755)

    result = hooks.install(repo)
    assert (hooks_dir / "pre-push.pre-linewatch").exists()
    assert any("Kept your existing pre-push hook" in note for note in result.notes)

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    commit(repo)
    out = git(repo, "push", "-q", "origin", "main", check=False)
    assert out.returncode == 0
    assert "linewatch: no findings." in out.stderr
    # The old hook got the git arguments and the refs on stdin.
    text = log.read_text()
    assert f"args: origin {remote}" in text
    assert "refs/heads/main" in text


def test_existing_hook_failure_still_blocks(repo):
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    legacy = repo / ".git" / "hooks" / "pre-commit"
    legacy.write_text("#!/bin/sh\necho legacy says no >&2\nexit 1\n")
    legacy.chmod(0o755)
    hooks.install(repo)
    out = commit(repo)
    assert out.returncode != 0
    assert "legacy says no" in out.stderr


def test_reinstall_is_idempotent(repo):
    hooks.install(repo)
    first = (repo / ".git" / "hooks" / "pre-commit").read_text()
    hooks.install(repo)
    assert (repo / ".git" / "hooks" / "pre-commit").read_text() == first
    assert not (repo / ".git" / "hooks" / "pre-commit.pre-linewatch").exists()


def test_refuses_to_overwrite_a_second_backup(repo):
    hooks_dir = repo / ".git" / "hooks"
    (hooks_dir / "pre-commit").write_text("#!/bin/sh\n")
    (hooks_dir / "pre-commit.pre-linewatch").write_text("#!/bin/sh\n")
    with pytest.raises(hooks.HookError, match="Merge them by hand"):
        hooks.install(repo)


def test_native_hook_without_linewatch_fails_open(repo):
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    path = repo / ".git" / "hooks" / "pre-commit"
    path.write_text(hooks.native_script("pre-commit", python="/nonexistent/python"))
    path.chmod(0o755)
    env = dict(os.environ, PATH="/usr/bin:/bin")
    (repo / "b.txt").write_text("b")
    git(repo, "add", "b.txt")
    out = subprocess.run(["git", "commit", "-q", "-m", "b"], cwd=repo, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "not installed, skipping" in out.stderr


# Husky

def test_husky_appends_to_existing_hook(repo):
    (repo / ".husky").mkdir()
    (repo / ".husky" / "pre-commit").write_text("npm test")
    result = hooks.install(repo)
    assert result.manager == "husky"
    text = (repo / ".husky" / "pre-commit").read_text()
    assert text.startswith("npm test\n\n# linewatch-managed")
    assert 'linewatch hook pre-commit "$@" || exit $?' in text
    assert (repo / ".husky" / "pre-push").stat().st_mode & 0o111
    assert any("npm install" in note for note in result.notes)

    hooks.install(repo)
    assert (repo / ".husky" / "pre-commit").read_text() == text


def test_husky8_new_files_get_the_shebang(repo):
    (repo / ".husky" / "_").mkdir(parents=True)
    (repo / ".husky" / "_" / "husky.sh").write_text("")
    hooks.install(repo, "husky")
    assert (repo / ".husky" / "pre-push").read_text().startswith("#!/usr/bin/env sh\n")


def test_husky_hook_runs_through_git(repo, tmp_path):
    write_repo_config(RepoConfig(hook="pre-commit"), repo)
    hooks.install(repo, "husky")
    git(repo, "config", "core.hooksPath", ".husky")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "linewatch"
    shim.write_text(f'#!/bin/sh\nexec {os.sys.executable} -m linewatch "$@"\n')
    shim.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    (repo / "c.txt").write_text("c")
    git(repo, "add", "c.txt")
    out = subprocess.run(["git", "commit", "-q", "-m", "c"], cwd=repo, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "linewatch: no findings." in out.stderr


# pre-commit framework

@pytest.mark.parametrize("original", [
    "repos:\n-   repo: https://github.com/psf/black\n    rev: 24.1.0\n    hooks:\n    -   id: black\n",
    "# team hooks\nrepos:\n  - repo: https://github.com/psf/black\n    rev: 24.1.0\n    hooks:\n      - id: black\n",
    "repos: []\n",
    "default_stages: [pre-commit]\nrepos:\n",
])
def test_pre_commit_config_is_appended(original):
    text = hooks.add_to_pre_commit_config(original)
    assert text.startswith(original.rstrip("[]\n").rstrip())
    data = yaml.safe_load(text)
    ids = [h["id"] for r in data["repos"] for h in r["hooks"]]
    assert ids[-2:] == ["linewatch-pre-commit", "linewatch-pre-push"]
    assert "# team hooks" in text or not original.startswith("#")


def test_pre_commit_config_not_ending_with_repos_is_left_alone():
    assert hooks.add_to_pre_commit_config("repos: []\nfail_fast: true\n") is None


def test_pre_commit_install_writes_config_and_explains(repo, monkeypatch):
    monkeypatch.setattr(hooks.shutil, "which", lambda name: None)
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n")
    result = hooks.install(repo)
    assert result.manager == "pre-commit"
    assert any("pre-commit install --hook-type pre-commit --hook-type pre-push" in n
               for n in result.notes)
    hooks.install(repo)
    text = (repo / ".pre-commit-config.yaml").read_text()
    assert text.count("linewatch-pre-commit") == 1


def test_pre_commit_install_refuses_when_it_cannot_append(repo):
    (repo / ".pre-commit-config.yaml").write_text("repos: []\nfail_fast: true\n")
    with pytest.raises(hooks.HookError, match="by hand"):
        hooks.install(repo)


def test_pre_commit_entry_fails_open_without_linewatch(tmp_path):
    entry = hooks.PRE_COMMIT_ENTRY.format(hook="pre-commit")
    out = subprocess.run(entry, shell=True, env={"PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True)
    assert out.returncode == 0


# linewatch hook

def test_run_hook_without_team_config_does_nothing(repo, capsys):
    assert hooks.run_hook("pre-push", cwd=repo) == 0
    assert capsys.readouterr().err == ""


def test_run_hook_outside_a_repo_fails_open(tmp_path, env, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert hooks.run_hook("pre-push", cwd=plain) == 0
    assert "skipping the review" in capsys.readouterr().err
