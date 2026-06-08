"""Tests for the Step 2 dummy server (health + basic chat completions).

These run against the in-memory FastAPI app using TestClient so that CI
exercises the actual endpoints introduced in Phase 0 Step 2 without needing
a live uvicorn process or external backends.
"""

from fastapi.testclient import TestClient

from tiny_llm_proxy.server import DUMMY_PROVIDERS, app

client = TestClient(app)


def test_health_endpoint():
    """GET /health returns the expected stub shape."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["providers"] == DUMMY_PROVIDERS
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
