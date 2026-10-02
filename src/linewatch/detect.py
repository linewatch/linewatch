"""Detect the LLMs available on this machine."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
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
    lms: str | None = None  # LM Studio CLI, which can start the server
    server_running: bool = True


LMSTUDIO_LABEL = "Bionic (LM Studio)"

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


def find_lms(home: Path | None = None, which=shutil.which) -> str | None:
    """The LM Studio CLI. The app is called Bionic on macOS now, and keeps
    its CLI in ~/.lmstudio/bin, which is often not on PATH."""
    found = which("lms")
    if found:
        return found
    candidate = (home or Path.home()) / ".lmstudio" / "bin" / "lms"
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _lms_json(lms: str, *args: str) -> object | None:
    try:
        out = subprocess.run([lms, *args, "--json"], capture_output=True, text=True, timeout=10)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def detect_lmstudio(
    base_url: str = LMSTUDIO_URL, timeout: float = PROBE_TIMEOUT, lms: str | None = None
) -> Backend | None:
    """Bionic (LM Studio): from its server, or from its CLI when the server is stopped."""
    data = _get_json(f"{base_url}/api/v0/models", timeout)
    if isinstance(data, dict):
        # The native API says which models are for chat and which are embeddings.
        models = [m["id"] for m in data.get("data", [])
                  if isinstance(m, dict) and "id" in m and m.get("type") in ("llm", "vlm")]
        return Backend("lmstudio", LMSTUDIO_LABEL, models=models, base_url=base_url, lms=lms)
    data = _get_json(f"{base_url}/v1/models", timeout)
    if isinstance(data, dict):
        models = [m["id"] for m in data.get("data", [])
                  if isinstance(m, dict) and "id" in m and "embed" not in m["id"]]
        return Backend("lmstudio", LMSTUDIO_LABEL, models=models, base_url=base_url, lms=lms)

    if lms is None:
        return None
    listing = _lms_json(lms, "ls")
    if not isinstance(listing, list):
        return None
    models = [m["modelKey"] for m in listing
              if isinstance(m, dict) and m.get("type") == "llm" and m.get("modelKey")]
    return Backend("lmstudio", LMSTUDIO_LABEL, models=models, base_url=base_url,
                   lms=lms, server_running=False)


def start_lmstudio_server(lms: str) -> str | None:
    """Start the Bionic server. Returns an error message, or None when it runs."""
    try:
        out = subprocess.run([lms, "server", "start"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if out.returncode != 0:
        return (out.stderr or out.stdout).strip() or "lms server start failed"
    return None


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
    local = (detect_ollama(), detect_lmstudio(lms=find_lms()))
    backends = [b for b in local if b is not None]
    backends += detect_api_keys(env)
    backends += detect_clis()
    return backends
