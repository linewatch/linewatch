import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from linewatch import detect


@pytest.fixture
def fake_server():
    """Serve fixed JSON bodies by path on a random local port."""
    routes = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in routes:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(routes[self.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield routes, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_detect_ollama_lists_models(fake_server):
    routes, url = fake_server
    routes["/api/tags"] = {"models": [{"name": "qwen2.5-coder:14b"}, {"name": "llama3:8b"}]}
    backend = detect.detect_ollama(url)
    assert backend.provider == "ollama"
    assert backend.models == ["qwen2.5-coder:14b", "llama3:8b"]


def test_detect_lmstudio_lists_models(fake_server):
    routes, url = fake_server
    routes["/v1/models"] = {"data": [{"id": "deepseek-coder"}]}
    assert detect.detect_lmstudio(url).models == ["deepseek-coder"]


def test_detect_server_not_running():
    assert detect.detect_ollama("http://127.0.0.1:9", timeout=0.2) is None


def test_detect_server_wrong_response(fake_server):
    _, url = fake_server
    assert detect.detect_lmstudio(url) is None


def test_detect_api_keys():
    env = {
        "ANTHROPIC_API_KEY": "sk-ant",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "g1",
        "GOOGLE_API_KEY": "g2",
        "AZURE_OPENAI_API_KEY": "az",
    }
    found = detect.detect_api_keys(env)
    # Empty keys are ignored, Gemini is listed once, Azure needs its endpoint.
    assert [(b.provider, b.api_key_env) for b in found] == [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
    ]


def test_detect_azure_with_endpoint():
    env = {"AZURE_OPENAI_API_KEY": "az", "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com"}
    (backend,) = detect.detect_api_keys(env)
    assert backend.base_url == "https://x.openai.azure.com"


def test_detect_clis():
    found = detect.detect_clis(which=lambda name: f"/usr/local/bin/{name}")
    assert [(b.provider, b.command) for b in found] == [
        ("claude-code", "/usr/local/bin/claude"),
        ("codex", "/usr/local/bin/codex"),
        ("antigravity", "/usr/local/bin/agy"),
    ]
    assert detect.detect_clis(which=lambda name: None) == []


def test_lmstudio_native_api_skips_embedding_models(fake_server):
    routes, url = fake_server
    routes["/api/v0/models"] = {"data": [
        {"id": "qwen/qwen3.8-27b", "type": "llm"},
        {"id": "google/gemma-4-31b-qat", "type": "vlm"},
        {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings"},
    ]}
    backend = detect.detect_lmstudio(url)
    assert backend.models == ["qwen/qwen3.8-27b", "google/gemma-4-31b-qat"]
    assert backend.label == "Bionic (LM Studio)" and backend.server_running


LMS_LS = """\
[ "$1 $2" = "ls --json" ] || exit 1
echo '[{"type":"llm","modelKey":"qwen/qwen3.8-27b"},{"type":"embedding","modelKey":"nomic-embed"}]'
"""


def test_lmstudio_with_stopped_server_found_through_its_cli(tmp_path):
    from conftest import fake_tool

    lms = fake_tool(tmp_path / ".lmstudio" / "bin", "lms", LMS_LS)
    assert detect.find_lms(home=tmp_path, which=lambda name: None) == str(lms)
    backend = detect.detect_lmstudio("http://127.0.0.1:9", timeout=0.2, lms=str(lms))
    assert backend.models == ["qwen/qwen3.8-27b"]
    assert not backend.server_running and backend.lms == str(lms)


def test_lmstudio_not_installed(tmp_path):
    assert detect.find_lms(home=tmp_path, which=lambda name: None) is None
    assert detect.detect_lmstudio("http://127.0.0.1:9", timeout=0.2, lms=None) is None


def test_start_lmstudio_server(tmp_path):
    from conftest import fake_tool

    ok = fake_tool(tmp_path / "ok", "lms", '[ "$1 $2" = "server start" ]\n')
    bad = fake_tool(tmp_path / "bad", "lms", 'echo "port in use" >&2; exit 1\n')
    assert detect.start_lmstudio_server(str(ok)) is None
    assert detect.start_lmstudio_server(str(bad)) == "port in use"
