"""The provider calls, with the SDK clients replaced by fakes."""

import json
from types import SimpleNamespace as NS

import pytest
from conftest import fake_tool

from linewatch import llm
from linewatch.config import UserConfig

SCHEMA = {"type": "object"}
ANSWER = {"findings": []}


class Recorder:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def anthropic_response(text=json.dumps(ANSWER), stop_reason="end_turn"):
    return NS(stop_reason=stop_reason, content=[NS(type="text", text=text)])


@pytest.fixture
def fake_anthropic(monkeypatch):
    import anthropic

    created = Recorder(anthropic_response())
    beta = Recorder(anthropic_response())
    clients = []

    def make(**kwargs):
        clients.append(kwargs)
        return NS(messages=NS(create=created), beta=NS(messages=NS(create=beta)))

    monkeypatch.setattr(anthropic, "Anthropic", make)
    return NS(create=created, beta=beta, clients=clients)


def test_anthropic_current_model_uses_fallbacks_and_effort(fake_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    user = UserConfig(provider="anthropic", model="claude-opus-5-5", api_key_env="ANTHROPIC_API_KEY")
    assert llm.complete(user, "sys", "prompt", SCHEMA) == ANSWER
    (call,) = fake_anthropic.beta.calls
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "medium"}
    assert call["system"] == "sys"
    assert fake_anthropic.clients[0]["api_key"] == "sk-env"


def test_anthropic_older_model_uses_plain_create(fake_anthropic):
    user = UserConfig(provider="anthropic", model="claude-haiku-4-5", api_key="sk-typed")
    llm.complete(user, "sys", "prompt", SCHEMA)
    (call,) = fake_anthropic.create.calls
    assert "fallbacks" not in call and "effort" not in call["output_config"]
    assert fake_anthropic.beta.calls == []


@pytest.mark.parametrize("stop_reason, message", [("refusal", "declined"), ("max_tokens", "cut off")])
def test_anthropic_bad_stop_reasons(fake_anthropic, stop_reason, message):
    fake_anthropic.beta.response = anthropic_response(stop_reason=stop_reason)
    user = UserConfig(provider="anthropic", model="claude-opus-5-5", api_key="k")
    with pytest.raises(llm.ModelError, match=message):
        llm.complete(user, "sys", "prompt", SCHEMA)


def test_missing_key_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    user = UserConfig(provider="openai", model="m", api_key_env="OPENAI_API_KEY")
    with pytest.raises(llm.ModelError, match=r"\$OPENAI_API_KEY is not set"):
        llm.complete(user, "sys", "prompt", SCHEMA)


@pytest.fixture
def fake_openai(monkeypatch):
    import openai

    message = NS(content=json.dumps(ANSWER), refusal=None)
    create = Recorder(NS(choices=[NS(message=message, finish_reason="stop")]))
    clients = []

    def make(kind):
        def factory(**kwargs):
            clients.append((kind, kwargs))
            return NS(chat=NS(completions=NS(create=create)))
        return factory

    monkeypatch.setattr(openai, "OpenAI", make("openai"))
    monkeypatch.setattr(openai, "AzureOpenAI", make("azure"))
    return NS(create=create, clients=clients, message=message)


def test_ollama_uses_the_openai_compatible_api(fake_openai):
    user = UserConfig(provider="ollama", model="qwen", base_url="http://localhost:11434/")
    assert llm.complete(user, "sys", "prompt", SCHEMA) == ANSWER
    kind, kwargs = fake_openai.clients[0]
    assert kind == "openai" and kwargs["base_url"] == "http://localhost:11434/v1"
    (call,) = fake_openai.create.calls
    assert call["response_format"]["json_schema"]["schema"] == SCHEMA
    assert call["messages"][0] == {"role": "system", "content": "sys"}


def test_azure_uses_endpoint_and_deployment(fake_openai):
    user = UserConfig(provider="azure-openai", model="my-deploy",
                      base_url="https://x.openai.azure.com", api_key="az")
    llm.complete(user, "sys", "prompt", SCHEMA)
    kind, kwargs = fake_openai.clients[0]
    assert kind == "azure" and kwargs["azure_endpoint"] == "https://x.openai.azure.com"
    assert fake_openai.create.calls[0]["model"] == "my-deploy"


def test_openai_refusal(fake_openai):
    fake_openai.message.refusal = "no"
    user = UserConfig(provider="openai", model="m", api_key="k")
    with pytest.raises(llm.ModelError, match="declined"):
        llm.complete(user, "sys", "prompt", SCHEMA)


def test_invalid_json_answer(fake_openai):
    fake_openai.message.content = "not json"
    user = UserConfig(provider="openai", model="m", api_key="k")
    with pytest.raises(llm.ModelError, match="not valid JSON"):
        llm.complete(user, "sys", "prompt", SCHEMA)


def test_sdk_errors_become_model_errors(monkeypatch):
    import openai

    def boom(**kwargs):
        raise ConnectionError("refused")
    monkeypatch.setattr(openai, "OpenAI", boom)
    user = UserConfig(provider="lmstudio", model="m", base_url="http://localhost:1234")
    with pytest.raises(llm.ModelError, match="lmstudio: ConnectionError: refused"):
        llm.complete(user, "sys", "prompt", SCHEMA)


def test_gemini(monkeypatch):
    from google import genai

    create = Recorder(NS(text=json.dumps(ANSWER)))
    monkeypatch.setattr(genai, "Client", lambda **kw: NS(models=NS(generate_content=create)))
    user = UserConfig(provider="gemini", model="g", api_key="k")
    assert llm.complete(user, "sys", "prompt", SCHEMA) == ANSWER
    config = create.calls[0]["config"]
    assert config.system_instruction == "sys"
    assert config.response_json_schema == SCHEMA


CLAUDE_SCRIPT = """\
# Fake claude CLI: record the arguments and stdin, answer like `claude -p --output-format json`.
printf '%s\\n' "$@" > "$(dirname "$0")/args.txt"
cat > "$(dirname "$0")/stdin.txt"
echo '{"type":"result","is_error":false,"result":"{}","structured_output":{"findings":[]}}'
"""


def test_claude_code_cli(tmp_path):
    cli = fake_tool(tmp_path / "bin", "claude", CLAUDE_SCRIPT)
    user = UserConfig(provider="claude-code", command=str(cli), model="claude-opus-5-5")
    assert llm.complete(user, "sys", "the diff", SCHEMA) == ANSWER
    args = (tmp_path / "bin" / "args.txt").read_text().splitlines()
    assert args[:3] == ["-p", "--output-format", "json"]
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert (tmp_path / "bin" / "stdin.txt").read_text() == "the diff"


def test_claude_code_cli_error(tmp_path):
    cli = fake_tool(tmp_path / "bin", "claude",
                    'echo \'{"type":"result","is_error":true,"result":"Not logged in"}\'\n')
    user = UserConfig(provider="claude-code", command=str(cli))
    with pytest.raises(llm.ModelError, match="Not logged in"):
        llm.complete(user, "sys", "prompt", SCHEMA)


def test_stopped_local_server_gets_a_hint(monkeypatch):
    import httpx2 as httpx
    import openai

    def refuse(**kwargs):
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:1234/v1"))
    client = NS(chat=NS(completions=NS(create=refuse)))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    user = UserConfig(provider="lmstudio", model="m", base_url="http://localhost:1234")
    with pytest.raises(llm.ModelError, match="Bionic .* is not running.*lms server start"):
        llm.complete(user, "sys", "prompt", SCHEMA)


def test_bionic_reasoning_model_answer_in_reasoning_content(fake_openai):
    fake_openai.message.content = ""
    fake_openai.message.reasoning_content = json.dumps(ANSWER)
    user = UserConfig(provider="lmstudio", model="qwen/qwen3.8-27b", base_url="http://localhost:1234")
    assert llm.complete(user, "sys", "prompt", SCHEMA) == ANSWER


def test_free_text_reasoning_is_not_an_answer(fake_openai):
    fake_openai.message.content = ""
    fake_openai.message.reasoning_content = "Let me think about this diff..."
    user = UserConfig(provider="lmstudio", model="m", base_url="http://localhost:1234")
    with pytest.raises(llm.ModelError, match="empty answer"):
        llm.complete(user, "sys", "prompt", SCHEMA)
