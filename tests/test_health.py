"""Trivial placeholder test for health / basic server.

This test is intentionally minimal so the early CI skeleton (scaffolded in
Phase 0 Step 1 per DESIGN.md) can run on every PR immediately, even before
the real server exists.

Later steps (especially Step 2 and Step 12) will expand this into real
checks against the dummy / real endpoints (using TestClient or in-process
uvicorn + httpx).
"""


def test_health_placeholder():
    """Placeholder asserting the test harness works.

    TODO (Step 2+): replace or augment with actual:
        from fastapi.testclient import TestClient
        from tiny_llm_proxy.server import app
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "providers" in resp.json()
    """
    assert True
