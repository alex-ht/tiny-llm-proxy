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


def test_dummy_chat_completions_non_stream(monkeypatch):
    """Non-stream path now does real forwarding (Step 5).

    We patch forward_request so the test does not require a live backend
    (LM Studio / OpenRouter). This still exercises the full routing + forward
    call path inside the endpoint.
    """
    from unittest.mock import AsyncMock

    async def _fake_forward(provider, body, **kwargs):
        return {
            "status_code": 200,
            "json": {
                "id": "chatcmpl-patched-123",
                "object": "chat.completion",
                "created": 1712345678,
                "model": body.get("model", "patched"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "patched real-forward dummy response (Step 5 test)",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            "duration_ms": 12.3,
        }

    monkeypatch.setattr(
        "tiny_llm_proxy.forward.forward_request",
        AsyncMock(side_effect=_fake_forward),
    )

    payload = {
        "model": "lmstudio/dummy",
        "messages": [{"role": "user", "content": "hello step 5"}],
        "stream": False,
    }
    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["object"] == "chat.completion"
    assert "choices" in data
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert (
        "patched real-forward dummy response (Step 5 test)"
        in data["choices"][0]["message"]["content"]
    )
    assert "usage" in data
    assert resp.headers.get("x-request-id")
    assert data["id"].startswith("chatcmpl-patched-")
