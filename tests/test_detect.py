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
    assert [(b.provider, b.command) for b in found] == [("claude-code", "/usr/local/bin/claude")]
    assert detect.detect_clis(which=lambda name: None) == []
