"""The `linewatch init` setup wizard and `linewatch model`."""

from __future__ import annotations

import getpass
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from linewatch import hooks
from linewatch.config import (
    CATEGORY_SETTINGS,
    effective_hook,
    NO_MODEL,
    REPO_CONFIG_NAME,
    ConfigError,
    RepoConfig,
    UserConfig,
    load_repo_config,
    load_user_config,
    user_config_path,
    write_repo_config,
    write_user_config,
)
from linewatch.detect import UNTESTED, Backend, detect_all, start_lmstudio_server

# Suggested model when a provider has no model list to choose from.
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
}

HOOK_CHOICES = [
    ("pre-push (recommended: one review per push)", "pre-push"),
    ("pre-commit", "pre-commit"),
    ("both", "both"),
]

# Providers offered when the dev types in an API key: (provider, label, key env var)
KEY_PROVIDERS = [
    ("anthropic", "Anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OpenAI", "OPENAI_API_KEY"),
    ("gemini", "Gemini", "GEMINI_API_KEY"),
    ("azure-openai", "Azure OpenAI", "AZURE_OPENAI_API_KEY"),
]

LOCAL_MODEL_HELP = """\
To run a model locally, install one of these and load a model:
  - Ollama (untested): https://ollama.com, then `ollama pull <model>`
  - LM Studio: https://lmstudio.ai, then load a model and start the local server"""

DETERMINISTIC_NOTE = (
    "Linewatch will run gitleaks only, for leaked secrets. "
    "Run `linewatch model` once a model is available."
)


class WizardError(Exception):
    """Raised when the wizard cannot continue."""


class Prompter:
    """Asks questions on the terminal. Tests pass their own input and output."""

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        secret_fn: Callable[[str], str] = getpass.getpass,
    ):
        self.input = input_fn
        self.say = output_fn
        self.secret_input = secret_fn

    def ask(self, question: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            answer = self.input(f"{question}{suffix}: ").strip()
            if answer:
                return answer
            if default is not None:
                return default
            self.say("  Please enter a value.")

    def secret(self, question: str) -> str:
        while True:
            answer = self.secret_input(f"{question}: ").strip()
            if answer:
                return answer
            self.say("  Please enter a value.")

    def choose(self, question: str, options: list[str], default: int = 1) -> int:
        """Show a numbered list and return the 0-based index of the choice."""
        self.say(question)
        for i, option in enumerate(options, 1):
            self.say(f"  {i}) {option}")
        while True:
            answer = self.ask("Choose", str(default))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            self.say(f"  Enter a number from 1 to {len(options)}.")

    def confirm(self, question: str, default: bool = False) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self.input(f"{question} [{hint}]: ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.say("  Answer y or n.")


@dataclass
class ModelChoice:
    """One LLM the dev can pick: a local model, an API provider or a CLI."""

    label: str
    backend: Backend
    model: str | None = None

    @property
    def needs_input(self) -> bool:
        """True if picking this choice still requires the dev to name a model."""
        return (
            self.model is None
            and self.backend.command is None
            and self.backend.provider not in DEFAULT_MODELS
        )


def find_repo_root(cwd: Path | None = None) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise WizardError("Not inside a git repository. Run `linewatch init` from your repo.")
    return Path(out.stdout.strip())


def untested(provider: str) -> str:
    return " (untested)" if provider in UNTESTED else ""


def model_choices(backends: list[Backend]) -> tuple[list[ModelChoice], list[Backend]]:
    """Turn backends into choices: one per local model. Also return empty local servers."""
    choices, empty = [], []
    for b in backends:
        tag = untested(b.provider)
        if b.command:
            choices.append(ModelChoice(f"{b.label} ({b.command}){tag}", b))
        elif b.api_key_env:
            choices.append(ModelChoice(f"{b.label} (key in ${b.api_key_env}){tag}", b))
        elif b.models:
            state = "" if b.server_running else " (server not running)"
            choices += [ModelChoice(f"{b.label}: {m}{state}{tag}", b, m) for m in b.models]
        else:
            empty.append(b)
    return choices, empty


def to_user_config(choice: ModelChoice, model: str | None) -> UserConfig:
    b = choice.backend
    return UserConfig(
        provider=b.provider,
        model=model,
        base_url=b.base_url,
        api_key_env=b.api_key_env,
        command=b.command,
    )


def finish_choice(p: Prompter, choice: ModelChoice) -> UserConfig:
    """Ask for the model name when the choice doesn't already include one."""
    b = choice.backend
    if choice.model is not None:
        model = choice.model
    elif b.command:
        model = p.ask("Model (leave empty for the CLI default)", "") or None
    else:
        prompt = "Deployment name" if b.provider == "azure-openai" else "Model"
        model = p.ask(prompt, DEFAULT_MODELS.get(b.provider))
    if not b.server_running and b.lms:
        offer_server_start(p, b)
    return to_user_config(choice, model)


def offer_server_start(p: Prompter, b: Backend) -> None:
    if p.confirm(f"The {b.label} server is not running. Start it now?", default=True):
        error = start_lmstudio_server(b.lms)
        if error is None:
            p.say(f"Started the {b.label} server. The model loads on the first review.")
            return
        p.say(f"Could not start it: {error}")
    p.say(f"Reviews skip the model until the server runs. Start it with `{b.lms} server start`.")


def choose_model(
    p: Prompter, detect: Callable[[], list[Backend]] = detect_all
) -> UserConfig:
    """Use cases 2, 3 and 4: several, one or no LLM found."""
    while True:
        p.say("Looking for LLMs...")
        choices, empty = model_choices(detect())
        for b in empty:
            p.say(f"Found {b.label} at {b.base_url}, but it has no models loaded.")

        if len(choices) > 1:
            index = p.choose("Which LLM should review your code?", [c.label for c in choices])
            return finish_choice(p, choices[index])
        if len(choices) == 1:
            if p.confirm(f"Found one LLM: {choices[0].label}. Use it?", default=True):
                return finish_choice(p, choices[0])
        else:
            p.say("No LLM found.")

        config = no_model_found(p)
        if config is not None:
            return config


def no_model_found(p: Prompter) -> UserConfig | None:
    """Offer the three ways out. Returns None to look for models again."""
    options = [
        "Set an API key",
        "Install a local model",
        "Run gitleaks only, for leaked secrets, until a model is added",
    ]
    index = p.choose("How do you want to continue?", options)
    if index == 0:
        return enter_api_key(p)
    if index == 1:
        p.say(LOCAL_MODEL_HELP)
        if p.confirm("Look for models again now?", default=True):
            return None
    p.say(DETERMINISTIC_NOTE)
    return UserConfig(provider=NO_MODEL)


def enter_api_key(p: Prompter) -> UserConfig:
    provider, label, key_env = KEY_PROVIDERS[
        p.choose("Which provider?", [label + untested(provider) for provider, label, _ in KEY_PROVIDERS])
    ]
    p.say(f"The key is stored in your user config, readable only by you. "
          f"You can also set ${key_env} instead.")
    api_key = p.secret(f"{label} API key")
    base_url = None
    if provider == "azure-openai":
        base_url = p.ask("Endpoint (https://<resource>.openai.azure.com)")
        model = p.ask("Deployment name")
    else:
        model = p.ask("Model", DEFAULT_MODELS.get(provider))
    return UserConfig(provider=provider, model=model, base_url=base_url, api_key=api_key)


def choose_hook(p: Prompter) -> str:
    labels = [label for label, _ in HOOK_CHOICES]
    return HOOK_CHOICES[p.choose("When should Linewatch run?", labels)][1]


def choose_categories(p: Prompter, defaults: dict[str, str]) -> dict[str, str]:
    p.say(
        "For each category, choose the lowest severity that blocks a commit or push.\n"
        "`never` reports findings without blocking; `off` turns the category off."
    )
    options = "/".join(CATEGORY_SETTINGS)
    categories = {}
    for name, default in defaults.items():
        while True:
            answer = p.ask(f"  {name} ({options})", default).lower()
            if answer in CATEGORY_SETTINGS:
                categories[name] = answer
                break
            p.say(f"  Enter one of: {', '.join(CATEGORY_SETTINGS)}.")
    return categories


def auto_model(detect: Callable[[], list[Backend]] = detect_all) -> tuple[UserConfig, bool]:
    """Pick a model without questions. Returns the config and whether a model was found."""
    choices, _ = model_choices(detect())
    if len(choices) == 1 and not choices[0].needs_input:
        choice = choices[0]
        model = choice.model or DEFAULT_MODELS.get(choice.backend.provider)
        return to_user_config(choice, model), True
    return UserConfig(provider=NO_MODEL), False


def _load_user_config(path: Path) -> UserConfig | None:
    try:
        return load_user_config(path)
    except ConfigError:
        return None


def run_init(
    yes: bool = False,
    prompter: Prompter | None = None,
    repo_root: Path | None = None,
    detect: Callable[[], list[Backend]] = detect_all,
    user_config_file: Path | None = None,
) -> int:
    p = prompter or Prompter()
    user_file = user_config_file or user_config_path()
    try:
        root = repo_root or find_repo_root()
        if yes:
            return _init_without_questions(p, root, detect, user_file)

        p.say("Linewatch setup\n")
        repo_config = None
        if (root / REPO_CONFIG_NAME).exists():
            p.say(f"This repo already has {REPO_CONFIG_NAME} with the team rules.")
            if p.confirm("Replace it?", default=False):
                repo_config = RepoConfig()
        else:
            repo_config = RepoConfig()

        user_config = choose_model(p, detect)

        if repo_config is not None:
            p.say("")
            repo_config.hook = choose_hook(p)
            p.say("")
            repo_config.categories = choose_categories(p, repo_config.categories)
    except WizardError as exc:
        p.say(f"linewatch: {exc}")
        return 1
    except (KeyboardInterrupt, EOFError):
        p.say("\nSetup cancelled. Nothing was written.")
        return 130

    p.say("")
    if repo_config is not None:
        p.say(f"Wrote {write_repo_config(repo_config, root)} (commit this file).")
    _save_user_config(p, user_config, user_file)
    return _install_hooks(p, root, user_file)


def _init_without_questions(
    p: Prompter, root: Path, detect: Callable[[], list[Backend]], user_file: Path
) -> int:
    """Use case 5: join a repo that is already configured."""
    if (root / REPO_CONFIG_NAME).exists():
        try:
            load_repo_config(root)
        except ConfigError as exc:
            raise WizardError(str(exc))
        p.say(f"Using the team rules in {REPO_CONFIG_NAME}.")
    else:
        path = write_repo_config(RepoConfig(), root)
        p.say(f"No {REPO_CONFIG_NAME} found. Wrote the defaults to {path} (commit this file).")

    existing = _load_user_config(user_file)
    if existing is not None:
        p.say(f"Using your model from {user_file}.")
    else:
        user_config, found = auto_model(detect)
        if found:
            p.say(f"Using the only model found: {_describe(user_config)}.")
        else:
            p.say("Found several LLMs or none, so Linewatch starts in deterministic-only mode.")
            p.say(DETERMINISTIC_NOTE)
        _save_user_config(p, user_config, user_file)
    return _install_hooks(p, root, user_file)


def _install_hooks(p: Prompter, root: Path, user_file: Path) -> int:
    try:
        result = hooks.install(root)
        setting = effective_hook(load_repo_config(root), _load_user_config(user_file))
    except (hooks.HookError, ConfigError) as exc:
        p.say(f"linewatch: could not install the hooks: {exc}")
        return 1
    manager = {"native": "git hooks", "husky": "Husky", "pre-commit": "the pre-commit framework"}
    p.say(f"Installed the hooks with {manager[result.manager]}. Linewatch runs on {setting}.")
    for note in result.notes:
        p.say(f"  {note}")
    return 0


def run_model(
    prompter: Prompter | None = None,
    detect: Callable[[], list[Backend]] = detect_all,
    user_config_file: Path | None = None,
) -> int:
    """Use case 6: switch to another model without rerunning the wizard."""
    p = prompter or Prompter()
    user_file = user_config_file or user_config_path()
    existing = _load_user_config(user_file)
    if existing is not None:
        p.say(f"Current model: {_describe(existing)}")
    try:
        user_config = choose_model(p, detect)
    except (KeyboardInterrupt, EOFError):
        p.say("\nCancelled. Nothing was changed.")
        return 130
    _save_user_config(p, user_config, user_file)
    return 0


def _describe(config: UserConfig) -> str:
    if config.provider == NO_MODEL:
        return "none (deterministic-only mode)"
    return f"{config.provider}" + (f" / {config.model}" if config.model else "")


def _save_user_config(p: Prompter, config: UserConfig, path: Path) -> None:
    # Keep the dev's local hook override when the model changes.
    existing = _load_user_config(path)
    if existing is not None and config.hook is None:
        config.hook = existing.hook
    p.say(f"Wrote {write_user_config(config, path)} (your model choice; stays out of the repo).")
