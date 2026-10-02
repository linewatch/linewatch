"""Detect the LLMs available on this machine."""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping

OLLAMA_URL = "http://localhost:11434"
LMSTUDIO_URL = "http://localhost:1234"

PROBE_TIMEOUT = 1.0


@dataclass
class Backend:
    """One way of reaching a model: a local server, an API key or a CLI."""

    provider: str
    label: str
    models: list[str] = field(default_factory=list)
    base_url: str | None = None
    api_key_env: str | None = None
    command: str | None = None


# (provider, label, env var holding the key, extra env vars that must also be set)
API_PROVIDERS = [
    ("anthropic", "Anthropic API", "ANTHROPIC_API_KEY", ()),
    ("openai", "OpenAI API", "OPENAI_API_KEY", ()),
    ("gemini", "Gemini API", "GEMINI_API_KEY", ()),
    ("gemini", "Gemini API", "GOOGLE_API_KEY", ()),
    ("azure-openai", "Azure OpenAI", "AZURE_OPENAI_API_KEY", ("AZURE_OPENAI_ENDPOINT",)),
]

# (provider, label, executable)
CLIS = [
    ("claude-code", "Claude Code CLI", "claude"),
]


def _get_json(url: str, timeout: float) -> object | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def detect_ollama(base_url: str = OLLAMA_URL, timeout: float = PROBE_TIMEOUT) -> Backend | None:
    data = _get_json(f"{base_url}/api/tags", timeout)
    if not isinstance(data, dict):
        return None
    models = [m["name"] for m in data.get("models", []) if isinstance(m, dict) and "name" in m]
    return Backend("ollama", "Ollama (local)", models=models, base_url=base_url)


def detect_lmstudio(base_url: str = LMSTUDIO_URL, timeout: float = PROBE_TIMEOUT) -> Backend | None:
    data = _get_json(f"{base_url}/v1/models", timeout)
    if not isinstance(data, dict):
        return None
    models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
    return Backend("lmstudio", "LM Studio (local)", models=models, base_url=base_url)


def detect_api_keys(env: Mapping[str, str] | None = None) -> list[Backend]:
    env = os.environ if env is None else env
    found: list[Backend] = []
    seen: set[str] = set()
    for provider, label, key_env, required in API_PROVIDERS:
        if provider in seen or not env.get(key_env):
            continue
        if not all(env.get(name) for name in required):
            continue
        seen.add(provider)
        base_url = env.get("AZURE_OPENAI_ENDPOINT") if provider == "azure-openai" else None
        found.append(Backend(provider, label, api_key_env=key_env, base_url=base_url))
    return found


def detect_clis(which=shutil.which) -> list[Backend]:
    found = []
    for provider, label, executable in CLIS:
        path = which(executable)
        if path:
            found.append(Backend(provider, label, command=path))
    return found


def detect_all(env: Mapping[str, str] | None = None) -> list[Backend]:
    """Return every backend found, local servers first."""
    backends = [b for b in (detect_ollama(), detect_lmstudio()) if b is not None]
    backends += detect_api_keys(env)
    backends += detect_clis()
    return backends
