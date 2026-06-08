"""Provider-aware request forwarding (non-streaming path).

Step 5 (Phase 2): real httpx calls to the selected backend.

Follows the exact "Header & Auth Construction Rules" from DESIGN.md:
- Never forward any incoming client Authorization / X-*-Key / api-key style header.
- Only emit Authorization: Bearer <key> when the *resolved* key for the provider
  (after api_key_env lookup) is a non-empty string.
- If api_key is null/"" for the provider (lmstudio, llama.cpp, etc.), omit the
  header entirely (local servers are often picky about its presence).
- Provider extra_headers (e.g. OpenRouter Referer) are always added when that
  provider is selected.
- The rewritten model (after routing) is used in the body sent to the backend.
- Basic error passthrough: backend status + body is returned as-is.
- Duration timing is recorded (returned to caller for logging later).

A single reusable httpx.AsyncClient is used (created on first use).
"""

import time
from typing import Any

import httpx

from .config import Config

# Reusable async client (simple global for v1; can be attached to app.state later).
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=300.0)  # generous for long generations
    return _client


async def forward_request(
    provider_name: str,
    body: dict[str, Any],
    *,
    config: Config,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Forward a (non-streaming) chat completion request to the chosen backend.

    Returns a dict with keys:
        status_code: int
        json: the backend response (or error body)
        duration_ms: float
    """
    provider = config.get_provider(provider_name)
    base_url = provider["base_url"].rstrip("/")
    target_url = f"{base_url}/v1/chat/completions"

    # Start with a copy of the (already routed) body
    send_body = dict(body)

    # Build outgoing headers per the exact rules
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # 1. Never forward client auth headers (security + to avoid surprising local servers)
    #    (We don't copy any Authorization / api-key style from the incoming request here.)

    # 2. Only add Authorization when we have a non-empty resolved key for *this* provider
    api_key = provider.get("api_key")
    if api_key and str(api_key).strip():
        headers["Authorization"] = f"Bearer {api_key}"

    # 3. Provider-specific extra headers (OpenRouter Referer etc. are safe and required)
    extra = provider.get("extra_headers") or {}
    for k, v in extra.items():
        # Allow both "HTTP-Referer" and "http-referer" style in yaml
        headers[k] = str(v)

    # Caller-supplied (e.g. from the original request if we want to forward safe ones)
    if extra_headers:
        for k, v in extra_headers.items():
            # We are conservative: only add if not already set and looks safe
            if k.lower() not in {h.lower() for h in headers} and not any(
                x in k.lower() for x in ("auth", "key", "token", "authorization")
            ):
                headers[k] = v

    start = time.perf_counter()
    client = _get_client()

    try:
        resp = await client.post(target_url, json=send_body, headers=headers)
        duration_ms = (time.perf_counter() - start) * 1000.0
        # Try to return JSON body even on error status (OpenAI errors are JSON)
        try:
            data = resp.json()
        except Exception:
            data = {"error": {"message": resp.text or "empty response", "type": "proxy_error"}}

        return {
            "status_code": resp.status_code,
            "json": data,
            "duration_ms": duration_ms,
        }
    except httpx.RequestError as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status_code": 502,
            "json": {
                "error": {
                    "message": f"Failed to reach backend {provider_name}: {exc}",
                    "type": "proxy_error",
                }
            },
            "duration_ms": duration_ms,
        }
