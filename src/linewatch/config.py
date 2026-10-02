"""Read and write the repo config and the user config.

The repo config (`.linewatch.yaml`) is committed and holds the team rules.
The user config holds each dev's model choice, API keys and an optional local
override of the hook. It stays out of the repo.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

REPO_CONFIG_NAME = ".linewatch.yaml"

HOOKS = ("pre-commit", "pre-push", "both")
SCOPES = ("changed-lines", "changed-files")
SEVERITIES = ("critical", "warning", "info")
BLOCK_AT = SEVERITIES + ("never",)
CATEGORY_SETTINGS = BLOCK_AT + ("off",)  # "off" disables the category

# Provider value for deterministic-only mode: gitleaks and Semgrep, no model.
NO_MODEL = "none"

DEFAULT_CATEGORIES = {
    "security": "critical",
    "quality": "never",
    "style": "off",
}
DEFAULT_EXCLUDE = ["*.lock", "dist/**"]


class ConfigError(Exception):
    """Raised when a config file is missing values or holds invalid ones."""


@dataclass
class RepoConfig:
    hook: str = "pre-push"
    scope: str = "changed-lines"
    # category name -> block_at value, or "off"
    categories: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CATEGORIES))
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    max_diff_lines: int = 2000

    def to_yaml(self) -> str:
        lines = [
            "# Linewatch team rules. Commit this file.",
            "# Each dev's model choice lives in their user config, not here.",
            f"{'hook: ' + self.hook:<26}# pre-commit | pre-push | both",
            f"{'scope: ' + self.scope:<26}# changed-lines | changed-files",
            "categories:",
        ]
        for name, setting in self.categories.items():
            if setting == "off":
                lines.append(f"  {name}: off")
            else:
                lines += [f"  {name}:", f"{'    block_at: ' + setting:<26}# critical | warning | info | never"]
        lines.append("exclude:")
        lines += [f"  - {_quote(pattern)}" for pattern in self.exclude]
        lines.append(f"max_diff_lines: {self.max_diff_lines}")
        return "\n".join(lines) + "\n"


@dataclass
class UserConfig:
    provider: str  # NO_MODEL means deterministic-only mode
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None  # the key is read from this env var
    api_key: str | None = None  # or stored here, when the dev typed it in
    command: str | None = None
    hook: str | None = None  # local override of the team's hook

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _quote(value: str) -> str:
    return yaml.safe_dump(value, default_style='"').strip()


def _check(value, allowed, name):
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}, not {value!r}")
    return value


def parse_repo_config(data) -> RepoConfig:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("the file must be a mapping of settings")
    config = RepoConfig()
    if "hook" in data:
        config.hook = _check(data["hook"], HOOKS, "hook")
    if "scope" in data:
        config.scope = _check(data["scope"], SCOPES, "scope")
    if "categories" in data:
        categories = data["categories"] or {}
        if not isinstance(categories, dict):
            raise ConfigError("categories must be a mapping")
        config.categories = {}
        for name, value in categories.items():
            # YAML 1.1 reads an unquoted `off` as false.
            if value is False or value == "off":
                config.categories[name] = "off"
            elif isinstance(value, dict) and "block_at" in value:
                config.categories[name] = _check(value["block_at"], BLOCK_AT, f"{name}.block_at")
            else:
                raise ConfigError(f"category {name!r} needs `block_at` or `off`")
    if "exclude" in data:
        exclude = data["exclude"] or []
        if not isinstance(exclude, list) or not all(isinstance(p, str) for p in exclude):
            raise ConfigError("exclude must be a list of patterns")
        config.exclude = exclude
    if "max_diff_lines" in data:
        value = data["max_diff_lines"]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError("max_diff_lines must be a positive number")
        config.max_diff_lines = value
    return config


def load_repo_config(repo_root: Path) -> RepoConfig:
    path = repo_root / REPO_CONFIG_NAME
    try:
        return parse_repo_config(yaml.safe_load(path.read_text()))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}")
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}")


def write_repo_config(config: RepoConfig, repo_root: Path) -> Path:
    path = repo_root / REPO_CONFIG_NAME
    path.write_text(config.to_yaml())
    return path


def effective_hook(repo: RepoConfig, user: UserConfig | None) -> str:
    """The dev's local override wins over the team default."""
    if user is not None and user.hook:
        return user.hook
    return repo.hook


def hook_is_active(hook: str, setting: str) -> bool:
    return setting == "both" or setting == hook


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "linewatch" / "config.yaml"


def load_user_config(path: Path | None = None) -> UserConfig | None:
    """Return the user config, or None if there is none yet."""
    path = path or user_config_path()
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}")
    if not isinstance(data, dict) or not data.get("provider"):
        raise ConfigError(f"{path} has no provider")
    known = {k: data[k] for k in UserConfig.__dataclass_fields__ if k in data}
    if known.get("hook") is not None:
        _check(known["hook"], HOOKS, f"{path}: hook")
    return UserConfig(**known)


def write_user_config(config: UserConfig, path: Path | None = None) -> Path:
    path = path or user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create the file readable only by the dev, since it can hold API keys.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(yaml.safe_dump(config.to_dict(), sort_keys=False))
    path.chmod(0o600)
    return path
