import subprocess

import pytest
import yaml

from linewatch import wizard
from linewatch.config import load_repo_config, load_user_config, write_user_config, UserConfig
from linewatch.detect import Backend

OLLAMA = Backend("ollama", "Ollama (local)", models=["llama3:8b", "qwen2.5-coder:14b"],
                 base_url="http://localhost:11434")
OLLAMA_ONE = Backend("ollama", "Ollama (local)", models=["llama3:8b"],
                     base_url="http://localhost:11434")
OLLAMA_EMPTY = Backend("ollama", "Ollama (local)", base_url="http://localhost:11434")
ANTHROPIC = Backend("anthropic", "Anthropic API", api_key_env="ANTHROPIC_API_KEY")
OPENAI = Backend("openai", "OpenAI API", api_key_env="OPENAI_API_KEY")
CLAUDE = Backend("claude-code", "Claude Code CLI", command="/usr/local/bin/claude")


def prompter(answers, secrets=()):
    """A Prompter that replays answers and records everything shown."""
    answers, secrets = iter(answers), iter(secrets)
    shown = []

    def fake_input(prompt):
        shown.append(prompt)
        return next(answers)

    def fake_secret(prompt):
        shown.append(prompt)
        return next(secrets)

    p = wizard.Prompter(fake_input, shown.append, fake_secret)
    p.shown = shown
    return p


def detector(*rounds):
    """Return each list of backends in turn, one per detection round."""
    rounds = iter(rounds)
    return lambda: next(rounds)


@pytest.fixture(autouse=True)
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.fixture
def user_file(tmp_path):
    return tmp_path / "user" / "config.yaml"


def init(tmp_path, user_file, answers, *rounds, secrets=(), yes=False):
    p = prompter(answers, secrets)
    code = wizard.run_init(yes=yes, prompter=p, repo_root=tmp_path,
                           detect=detector(*rounds), user_config_file=user_file)
    return code, p


def raw_user(user_file):
    return yaml.safe_load(user_file.read_text())


# Use case 1 and 2: first setup, several LLMs found.

def test_first_setup_with_defaults(tmp_path, user_file):
    # model, hook, security, quality, style
    code, _ = init(tmp_path, user_file, [""] * 5, [OLLAMA, ANTHROPIC])
    assert code == 0
    repo = load_repo_config(tmp_path)
    assert repo.hook == "pre-push"
    assert repo.categories == {"security": "critical", "quality": "never", "style": "off"}
    assert raw_user(user_file) == {
        "provider": "ollama",
        "model": "llama3:8b",
        "base_url": "http://localhost:11434",
    }


def test_only_untested_providers_are_marked():
    choices, _ = wizard.model_choices([ANTHROPIC, CLAUDE])
    assert [c.label for c in choices] == [
        "Anthropic API (key in $ANTHROPIC_API_KEY) (untested)",
        "Claude Code CLI (/usr/local/bin/claude)",
    ]


def test_several_llms_lists_each_local_model(tmp_path, user_file):
    answers = ["2", "3", "warning", "info", "never"]
    code, p = init(tmp_path, user_file, answers, [OLLAMA, ANTHROPIC])
    assert code == 0
    assert "  1) Ollama (local): llama3:8b (untested)" in p.shown
    assert "  2) Ollama (local): qwen2.5-coder:14b (untested)" in p.shown
    assert raw_user(user_file)["model"] == "qwen2.5-coder:14b"
    repo = load_repo_config(tmp_path)
    assert repo.hook == "both"
    assert repo.categories == {"security": "warning", "quality": "info", "style": "never"}


def test_api_provider_uses_env_key_and_default_model(tmp_path, user_file):
    code, _ = init(tmp_path, user_file, ["3", ""] + [""] * 4, [OLLAMA, ANTHROPIC])
    assert code == 0
    assert raw_user(user_file) == {
        "provider": "anthropic",
        "model": wizard.DEFAULT_MODELS["anthropic"],
        "api_key_env": "ANTHROPIC_API_KEY",
    }


def test_invalid_answers_are_asked_again(tmp_path, user_file):
    answers = ["9", "x", "1", "", "high", "critical", "", ""]
    code, p = init(tmp_path, user_file, answers, [OLLAMA])
    assert code == 0
    assert any("1 to 2" in line for line in p.shown)
    assert any("Enter one of" in line for line in p.shown)


# Use case 3: one LLM found.

def test_one_llm_is_preselected_and_confirmed(tmp_path, user_file):
    # confirm, hook, security, quality, style
    code, p = init(tmp_path, user_file, [""] * 5, [OLLAMA_ONE])
    assert code == 0
    assert any("Found one LLM: Ollama (local): llama3:8b (untested). Use it?" in line for line in p.shown)
    assert raw_user(user_file)["model"] == "llama3:8b"


def test_one_cli_llm_model_is_optional(tmp_path, user_file):
    code, _ = init(tmp_path, user_file, [""] * 6, [CLAUDE])
    assert code == 0
    assert raw_user(user_file) == {"provider": "claude-code", "command": "/usr/local/bin/claude"}


def test_declining_the_one_llm_offers_the_ways_out(tmp_path, user_file):
    # decline, deterministic-only, hook, 3 categories
    code, p = init(tmp_path, user_file, ["n", "3"] + [""] * 4, [OLLAMA_ONE])
    assert code == 0
    assert raw_user(user_file) == {"provider": "none"}


# Use case 4: no LLM found.

def test_no_llm_set_an_api_key(tmp_path, user_file):
    answers = ["1", "2", "gpt-x"] + [""] * 4  # set key, OpenAI, model, hook, categories
    code, p = init(tmp_path, user_file, answers, [OLLAMA_EMPTY], secrets=["sk-typed"])
    assert code == 0
    assert any("no models loaded" in line for line in p.shown)
    assert raw_user(user_file) == {"provider": "openai", "model": "gpt-x", "api_key": "sk-typed"}


def test_no_llm_set_an_azure_key(tmp_path, user_file):
    answers = ["1", "4", "https://x.openai.azure.com", "my-deploy"] + [""] * 4
    code, _ = init(tmp_path, user_file, answers, [], secrets=["az-key"])
    assert code == 0
    assert raw_user(user_file) == {
        "provider": "azure-openai",
        "model": "my-deploy",
        "base_url": "https://x.openai.azure.com",
        "api_key": "az-key",
    }


def test_no_llm_install_local_model_then_detect_again(tmp_path, user_file):
    # install local model, look again (found one), confirm it, hook, categories
    answers = ["2", "y", ""] + [""] * 4
    code, p = init(tmp_path, user_file, answers, [], [OLLAMA_ONE])
    assert code == 0
    assert any("ollama pull" in line for line in p.shown)
    assert raw_user(user_file)["model"] == "llama3:8b"


def test_no_llm_install_local_model_later(tmp_path, user_file):
    code, _ = init(tmp_path, user_file, ["2", "n"] + [""] * 4, [])
    assert code == 0
    assert raw_user(user_file) == {"provider": "none"}


def test_no_llm_deterministic_only(tmp_path, user_file):
    code, p = init(tmp_path, user_file, ["3"] + [""] * 4, [])
    assert code == 0
    assert raw_user(user_file) == {"provider": "none"}
    assert (tmp_path / ".linewatch.yaml").exists()
    assert any("linewatch model" in line for line in p.shown)


# Existing team config during interactive init.

def test_keeps_existing_repo_config(tmp_path, user_file):
    (tmp_path / ".linewatch.yaml").write_text("hook: pre-commit\n")
    code, _ = init(tmp_path, user_file, ["n", ""], [OLLAMA])
    assert code == 0
    assert (tmp_path / ".linewatch.yaml").read_text() == "hook: pre-commit\n"
    assert user_file.exists()


def test_replaces_existing_repo_config(tmp_path, user_file):
    (tmp_path / ".linewatch.yaml").write_text("hook: pre-commit\n")
    code, _ = init(tmp_path, user_file, ["y", ""] + [""] * 4, [OLLAMA])
    assert code == 0
    assert load_repo_config(tmp_path).hook == "pre-push"


def test_keeps_local_hook_override(tmp_path, user_file):
    write_user_config(UserConfig(provider="ollama", model="old", hook="pre-commit"), user_file)
    code, _ = init(tmp_path, user_file, [""] * 5, [OLLAMA])
    assert code == 0
    assert raw_user(user_file)["hook"] == "pre-commit"
    assert raw_user(user_file)["model"] == "llama3:8b"


def test_ctrl_c_writes_nothing(tmp_path, user_file):
    def interrupt(prompt):
        raise KeyboardInterrupt

    p = wizard.Prompter(interrupt, lambda s: None)
    code = wizard.run_init(prompter=p, repo_root=tmp_path, detect=lambda: [OLLAMA],
                           user_config_file=user_file)
    assert code == 130
    assert not (tmp_path / ".linewatch.yaml").exists()
    assert not user_file.exists()


# Use case 5: init --yes.

def test_yes_uses_team_rules_and_the_only_model(tmp_path, user_file):
    (tmp_path / ".linewatch.yaml").write_text("hook: pre-commit\n")
    code, p = init(tmp_path, user_file, [], [OLLAMA_ONE], yes=True)
    assert code == 0
    assert (tmp_path / ".linewatch.yaml").read_text() == "hook: pre-commit\n"
    assert raw_user(user_file)["model"] == "llama3:8b"
    assert not any(line.endswith(": ") for line in p.shown)  # asked nothing


def test_yes_keeps_existing_user_config(tmp_path, user_file):
    write_user_config(UserConfig(provider="anthropic", model="m"), user_file)
    code, _ = init(tmp_path, user_file, [], [OLLAMA_ONE], yes=True)
    assert code == 0
    assert raw_user(user_file) == {"provider": "anthropic", "model": "m"}


@pytest.mark.parametrize("backends", [[], [OLLAMA], [OLLAMA_ONE, CLAUDE], [OPENAI]])
def test_yes_falls_back_to_deterministic_only(tmp_path, user_file, backends):
    # none found, several found, or one that still needs a model name
    code, p = init(tmp_path, user_file, [], backends, yes=True)
    assert code == 0
    assert raw_user(user_file) == {"provider": "none"}
    assert any("linewatch model" in line for line in p.shown)


def test_yes_with_one_api_provider_uses_default_model(tmp_path, user_file):
    code, _ = init(tmp_path, user_file, [], [ANTHROPIC], yes=True)
    assert code == 0
    assert raw_user(user_file)["model"] == wizard.DEFAULT_MODELS["anthropic"]


def test_yes_without_team_config_writes_defaults(tmp_path, user_file):
    code, _ = init(tmp_path, user_file, [], [OLLAMA_ONE], yes=True)
    assert code == 0
    assert load_repo_config(tmp_path).hook == "pre-push"


def test_yes_rejects_invalid_team_config(tmp_path, user_file):
    (tmp_path / ".linewatch.yaml").write_text("hook: sometimes\n")
    code, p = init(tmp_path, user_file, [], [OLLAMA_ONE], yes=True)
    assert code == 1
    assert any("hook must be one of" in line for line in p.shown)
    assert not user_file.exists()


# Use case 6: linewatch model.

def test_model_switches_and_keeps_hook_override(user_file):
    write_user_config(UserConfig(provider="ollama", model="llama3:8b", hook="pre-commit"), user_file)
    p = prompter(["3", ""])
    code = wizard.run_model(prompter=p, detect=lambda: [OLLAMA, ANTHROPIC],
                            user_config_file=user_file)
    assert code == 0
    assert any("Current model: ollama / llama3:8b" in line for line in p.shown)
    user = load_user_config(user_file)
    assert (user.provider, user.hook) == ("anthropic", "pre-commit")


# Git repository.

def test_not_a_git_repo(tmp_path_factory, user_file, monkeypatch):
    monkeypatch.chdir(tmp_path_factory.mktemp("plain"))
    p = prompter([])
    code = wizard.run_init(prompter=p, detect=lambda: [OLLAMA], user_config_file=user_file)
    assert code == 1
    assert any("Not inside a git repository" in line for line in p.shown)


def test_find_repo_root(tmp_path):
    (tmp_path / "sub").mkdir()
    assert wizard.find_repo_root(tmp_path / "sub") == tmp_path.resolve()


# Use case 1: init installs the hooks.

def test_init_installs_hooks(tmp_path, user_file):
    code, p = init(tmp_path, user_file, [""] * 5, [OLLAMA])
    assert code == 0
    for hook in ("pre-commit", "pre-push"):
        assert "linewatch-managed" in (tmp_path / ".git" / "hooks" / hook).read_text()
    assert any("Installed the hooks with git hooks. Linewatch runs on pre-push." in line
               for line in p.shown)


def test_init_yes_reports_local_override(tmp_path, user_file):
    write_user_config(UserConfig(provider="none", hook="both"), user_file)
    code, p = init(tmp_path, user_file, [], [], yes=True)
    assert code == 0
    assert any("Linewatch runs on both." in line for line in p.shown)


# Bionic (LM Studio) with its server stopped.

BIONIC_STOPPED = Backend("lmstudio", "Bionic (LM Studio)", models=["qwen/qwen3.8-27b"],
                         base_url="http://localhost:1234", lms="/x/lms", server_running=False)


@pytest.mark.parametrize("start_answer, error, expected", [
    ("", None, "Started the Bionic (LM Studio) server"),
    ("", "port in use", "Could not start it: port in use"),
    ("n", None, "Reviews skip the model until the server runs"),
])
def test_stopped_bionic_server_is_offered_to_start(tmp_path, user_file, monkeypatch,
                                                    start_answer, error, expected):
    started = []
    monkeypatch.setattr(wizard, "start_lmstudio_server", lambda lms: started.append(lms) or error)
    # confirm the one model, start answer, hook, 3 categories
    code, p = init(tmp_path, user_file, ["", start_answer] + [""] * 4, [BIONIC_STOPPED])
    assert code == 0
    assert any("qwen/qwen3.8-27b (server not running)" in line for line in p.shown)
    assert any(expected in line for line in p.shown)
    assert started == ([] if start_answer == "n" else ["/x/lms"])
    assert raw_user(user_file)["model"] == "qwen/qwen3.8-27b"
