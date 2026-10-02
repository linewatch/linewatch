import stat

import pytest
import yaml

from linewatch import config
from linewatch.config import ConfigError, RepoConfig, UserConfig


def test_default_repo_config_matches_the_documented_example(tmp_path):
    config.write_repo_config(RepoConfig(), tmp_path)
    text = (tmp_path / ".linewatch.yaml").read_text()
    assert "  style: off\n" in text
    assert yaml.safe_load(text) == {
        "hook": "pre-push",
        "scope": "changed-lines",
        "categories": {
            "security": {"block_at": "critical"},
            "quality": {"block_at": "never"},
            "style": False,  # YAML 1.1 reads `off` as false
        },
        "exclude": ["*.lock", "dist/**"],
        "max_diff_lines": 2000,
    }


def test_repo_config_round_trip(tmp_path):
    original = RepoConfig(
        hook="both",
        scope="changed-files",
        categories={"security": "warning", "quality": "off", "perf": "info"},
        exclude=["*.min.js", "vendor/**"],
        max_diff_lines=500,
    )
    config.write_repo_config(original, tmp_path)
    assert config.load_repo_config(tmp_path) == original


def test_parse_accepts_partial_config():
    parsed = config.parse_repo_config({"hook": "pre-commit"})
    assert parsed.hook == "pre-commit"
    assert parsed.categories == config.DEFAULT_CATEGORIES


def test_parse_accepts_quoted_off():
    parsed = config.parse_repo_config({"categories": {"style": "off"}})
    assert parsed.categories == {"style": "off"}


@pytest.mark.parametrize(
    "data, message",
    [
        ({"hook": "post-commit"}, "hook must be one of"),
        ({"scope": "everything"}, "scope must be one of"),
        ({"categories": {"security": {"block_at": "high"}}}, "security.block_at"),
        ({"categories": {"security": "critical"}}, "needs `block_at` or `off`"),
        ({"exclude": "*.lock"}, "exclude must be a list"),
        ({"max_diff_lines": 0}, "max_diff_lines"),
        (["hook"], "mapping"),
    ],
)
def test_parse_rejects_invalid_values(data, message):
    with pytest.raises(ConfigError, match=message):
        config.parse_repo_config(data)


def test_load_repo_config_reports_bad_yaml(tmp_path):
    (tmp_path / ".linewatch.yaml").write_text("hook: [unclosed\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        config.load_repo_config(tmp_path)


def test_user_config_round_trip_and_permissions(tmp_path):
    path = tmp_path / "linewatch" / "config.yaml"
    original = UserConfig(provider="openai", model="m", api_key="sk-secret", hook="pre-commit")
    config.write_user_config(original, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert config.load_user_config(path) == original


def test_load_user_config_missing_file(tmp_path):
    assert config.load_user_config(tmp_path / "nope.yaml") is None


def test_load_user_config_rejects_bad_hook(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("provider: ollama\nhook: sometimes\n")
    with pytest.raises(ConfigError, match="hook"):
        config.load_user_config(path)


def test_user_config_path_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.user_config_path() == tmp_path / "linewatch" / "config.yaml"
