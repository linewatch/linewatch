"""Send a review prompt to the chosen model and get structured JSON back."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from linewatch.config import UserConfig

DEFAULT_TIMEOUT = 180  # seconds per request; local models can be slow
AZURE_API_VERSION = "2024-10-21"

# Current Claude models: they take `effort` and server-side refusal fallbacks.
CLAUDE_CURRENT = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class ModelError(Exception):
    """The model could not be reached or gave no usable answer. Never blocks."""


def complete(user: UserConfig, system: str, prompt: str, schema: dict,
             timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Return the model's JSON answer, validated only as JSON."""
    provider = user.provider
    try:
        if provider == "anthropic":
            text = _anthropic(user, system, prompt, schema, timeout)
        elif provider in ("openai", "azure-openai", "lmstudio", "ollama"):
            text = _openai_compatible(user, system, prompt, schema, timeout)
        elif provider == "gemini":
            text = _gemini(user, system, prompt, schema, timeout)
        elif provider == "claude-code":
            return _claude_code(user, system, prompt, schema, timeout)
        elif provider == "codex":
            text = _codex(user, system, prompt, schema, timeout)
        elif provider == "antigravity":
            return _antigravity(user, system, prompt, schema, timeout)
        else:
            raise ModelError(f"unknown provider {provider!r}")
    except ModelError:
        raise
    except Exception as exc:  # SDK, network and timeout errors all fail open
        raise ModelError(f"{provider}: {type(exc).__name__}: {exc}") from exc
    try:
        return json.loads(text)
    except ValueError:
        raise ModelError(f"{provider}: the answer is not valid JSON")


def _api_key(user: UserConfig) -> str | None:
    if user.api_key:
        return user.api_key
    if user.api_key_env:
        key = os.environ.get(user.api_key_env)
        if not key:
            raise ModelError(f"${user.api_key_env} is not set")
        return key
    return None


def _anthropic(user, system, prompt, schema, timeout) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=_api_key(user), timeout=timeout, max_retries=1)
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    params = dict(
        model=user.model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if user.model in CLAUDE_CURRENT:
        output_config["effort"] = "medium"
        response = client.beta.messages.create(
            **params,
            output_config=output_config,
            # A declined request is re-run on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    else:
        response = client.messages.create(**params, output_config=output_config)
    if response.stop_reason == "refusal":
        raise ModelError("anthropic: the model declined to review this change")
    if response.stop_reason == "max_tokens":
        raise ModelError("anthropic: the answer was cut off")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ModelError("anthropic: empty answer")
    return text


def _openai_compatible(user, system, prompt, schema, timeout) -> str:
    import openai

    if user.provider == "azure-openai":
        client = openai.AzureOpenAI(
            api_key=_api_key(user),
            azure_endpoint=user.base_url,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", AZURE_API_VERSION),
            timeout=timeout,
            max_retries=1,
        )
    elif user.provider == "openai":
        client = openai.OpenAI(api_key=_api_key(user), timeout=timeout, max_retries=1)
    else:
        # Ollama and LM Studio serve an OpenAI-compatible API under /v1.
        client = openai.OpenAI(
            base_url=f"{user.base_url.rstrip('/')}/v1",
            api_key=user.provider,
            timeout=timeout,
            max_retries=0,
        )
    try:
        response = _chat(client, user, system, prompt, schema)
    except openai.APIConnectionError:
        if user.provider in LOCAL_SERVER_HINTS:
            raise ModelError(LOCAL_SERVER_HINTS[user.provider].format(url=user.base_url))
        raise
    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise ModelError(f"{user.provider}: the model declined to review this change")
    if choice.finish_reason == "length":
        raise ModelError(f"{user.provider}: the answer was cut off")
    text = choice.message.content or _structured_reasoning(choice.message)
    if not text:
        raise ModelError(f"{user.provider}: empty answer")
    return text


def _structured_reasoning(message) -> str | None:
    """Bionic (LM Studio) puts the structured answer of a reasoning model, such
    as Qwen 3.x, in `reasoning_content` and leaves `content` empty."""
    extra = getattr(message, "model_extra", None) or {}
    reasoning = getattr(message, "reasoning_content", None) or extra.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip().startswith("{"):
        return reasoning
    return None


LOCAL_SERVER_HINTS = {
    "lmstudio": "the Bionic (LM Studio) server at {url} is not running. "
                "Start it in the app or with `lms server start`",
    "ollama": "Ollama is not running at {url}. Start it with `ollama serve`",
}


def _chat(client, user, system, prompt, schema):
    return client.chat.completions.create(
        model=user.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "review", "schema": schema, "strict": True},
        },
    )


def _gemini(user, system, prompt, schema, timeout) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=_api_key(user),
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
    )
    response = client.models.generate_content(
        model=user.model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )
    if not response.text:
        raise ModelError("gemini: empty answer")
    return response.text


def _claude_code(user, system, prompt, schema, timeout) -> dict:
    command = [
        user.command or "claude", "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--system-prompt", system,
        # No tools, settings, hooks or MCP servers: the review only reads the prompt.
        "--tools", "",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if user.model:
        command += ["--model", user.model]
    try:
        out = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ModelError(f"claude-code: no answer within {timeout:.0f}s")
    except OSError as exc:
        raise ModelError(f"claude-code: {exc}")
    try:
        data = json.loads(out.stdout)
    except ValueError:
        detail = (out.stderr or out.stdout).strip().splitlines()
        raise ModelError(f"claude-code: {detail[-1] if detail else 'no output'}")
    if data.get("is_error") or not isinstance(data.get("structured_output"), dict):
        raise ModelError(f"claude-code: {data.get('result') or data.get('subtype') or 'no answer'}")
    return data["structured_output"]


def _codex(user, system, prompt, schema, timeout) -> str:
    with tempfile.TemporaryDirectory(prefix="linewatch-codex-") as tmp:
        schema_file, answer_file, workdir = Path(tmp, "schema.json"), Path(tmp, "answer.json"), Path(tmp, "work")
        schema_file.write_text(json.dumps(schema))
        workdir.mkdir()
        command = [
            user.command or "codex", "exec",
            "--output-schema", str(schema_file),
            "--output-last-message", str(answer_file),
            "-c", f"developer_instructions={json.dumps(system)}",
            # Read-only, in an empty folder, without the dev's config, rules or
            # session history: the review only reads the prompt.
            "--sandbox", "read-only",
            "--cd", str(workdir),
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--color", "never",
        ]
        if user.model:
            command += ["--model", user.model]
        command.append("-")  # the prompt comes from stdin
        try:
            out = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ModelError(f"codex: no answer within {timeout:.0f}s")
        except OSError as exc:
            raise ModelError(f"codex: {exc}")
        text = answer_file.read_text().strip() if answer_file.is_file() else ""
        if out.returncode != 0 or not text:
            detail = (out.stderr or out.stdout).strip().splitlines()
            raise ModelError(f"codex: {detail[-1] if detail else 'no answer'}")
        return text


# agy has no system prompt or no-tools option. Without this, Gemini sometimes
# tries a shell command, headless mode denies it, and no answer comes back.
AGY_NO_TOOLS = ("You have no tools in this run: don't run commands or read files. "
                "Everything you need is in this message.")


def _antigravity(user, system, prompt, schema, timeout) -> dict:
    command = [
        user.command or "agy",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--sandbox",
    ]
    if user.model:
        command += ["--model", user.model]
    # agy reads the prompt only from -p.
    command.append(f"-p={AGY_NO_TOOLS}\n\n{system}\n\n{prompt}")
    # A missing answer is usually a denied tool call, so try once more.
    for attempt in range(2):
        with tempfile.TemporaryDirectory(prefix="linewatch-agy-") as workdir:
            try:
                out = subprocess.run(command, cwd=workdir, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise ModelError(f"antigravity: no answer within {timeout:.0f}s")
            except OSError as exc:
                raise ModelError(f"antigravity: {exc}")
        try:
            data = json.loads(out.stdout)
        except ValueError:
            data = {}
        if data.get("status") == "SUCCESS" and isinstance(data.get("structured_output"), dict):
            return data["structured_output"]
    detail = out.stderr.strip().splitlines()
    raise ModelError(f"antigravity: {detail[-1] if detail else data.get('status') or 'no answer'}")
