import os
import subprocess

import pytest


def git(root, *args, check=True, env=None):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=check, env=env)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Keep the real user config and git settings out of the tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PRE_COMMIT_FROM_REF",
                 "PRE_COMMIT_TO_REF", "PRE_COMMIT_REMOTE_NAME"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def make_repo(isolated):
    def make(name="repo"):
        root = isolated / name
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "dev@example.com")
        git(root, "config", "user.name", "Dev")
        git(root, "config", "commit.gpgsign", "false")
        return root
    return make


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def commit_all(root, message="change"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def fake_tool(directory, name, script):
    """Put an executable shell script called `name` in `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return path


@pytest.fixture
def no_gitleaks(monkeypatch):
    from linewatch import gitleaks
    monkeypatch.setattr(gitleaks, "available", lambda: False)
