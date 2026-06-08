"""Tests for the config-aware dummy server (Phase 1 / Step 3).

Health now reports providers loaded from config (usually via config.example.yaml).
The chat endpoint remains a non-streaming dummy until Phase 2/3.
"""

from fastapi.testclient import TestClient

from tiny_llm_proxy.config import load_config
from tiny_llm_proxy.server import create_app

# Load once using the normal rules (will find config.example.yaml in the repo root).
# Using create_app() makes the tests exercise the new factory + Config path.
_test_cfg = load_config()
client = TestClient(create_app(_test_cfg))


def test_health_endpoint():
    """GET /health returns providers from the loaded Config (Step 3)."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # We loaded via config.example.yaml (or defaults), so both known providers must appear.
    assert "lmstudio" in data["providers"]
    assert "openrouter" in data["providers"]
    assert "request_id" in data
    assert resp.headers.get("x-request-id")  # middleware always adds it


def test_v1_health_endpoint():
    """GET /v1/health also works (alias)."""
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_dummy_chat_completions_non_stream():
    """POST /v1/chat/completions returns a valid OpenAI-shaped dummy response.

    (Non-streaming only in Step 2. Streaming + real backends come later.)
    """
    payload = {
        "model": "lmstudio/dummy",
        "messages": [{"role": "user", "content": "hello step 2"}],
        "stream": False,
    }
    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["object"] == "chat.completion"
    assert "choices" in data
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert "dummy response from tiny-llm-proxy" in data["choices"][0]["message"]["content"]
    assert "usage" in data
    assert resp.headers.get("x-request-id")
    assert data["id"].startswith("chatcmpl-dummy-")
