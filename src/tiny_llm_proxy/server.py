"""FastAPI application and endpoint definitions.

The server is config-aware (Step 3), has routing (Step 4), and real non-stream
forwarding (Step 5). This step (6) adds end-to-end wiring for the non-stream
path + basic console observability (struct-ish INFO logs for request start/complete
with req_id, provider, model, duration, token counts).

Streaming + message logging (the core value) come in Phase 3.
Request ID middleware remains for correlation.
"""

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from .utils import generate_request_id

if TYPE_CHECKING:
    from .config import Config  # for type hints only (avoids circular at runtime)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request_id to every request (in state) and echo it in the response header."""

    async def dispatch(self, request: Request, call_next):
        req_id = generate_request_id()
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


def create_app(config: Optional["Config"] = None) -> FastAPI:
    """Application factory.

    If config is None, load_config() is called (respects TINYLLM_CONFIG env
    and the normal search order including config.example.yaml).
    The returned app has app.state.config populated for later use by
    routing/forwarding/logging.
    """
    if config is None:
        from .config import load_config

        config = load_config()

    # Respect config log_level for our application logs (uvicorn gets it separately in main)
    log_level = getattr(logging, str(config.log_level).upper(), logging.INFO)
    logging.getLogger("tiny_llm_proxy").setLevel(log_level)

    app = FastAPI(
        title="tiny-llm-proxy",
        version="0.1.0",
        description=(
            "Tiny OpenAI-compatible proxy with local message-format logging "
            f"(config: {config.config_path or 'defaults'})"
        ),
    )
    app.state.config = config
    app.add_middleware(RequestIDMiddleware)

    provider_names = list(config.providers.keys())

    @app.get("/health")
    @app.get("/v1/health")
    async def health(request: Request) -> dict:
        """Health check. Reports the providers that are actually configured."""
        return {
            "status": "ok",
            "providers": provider_names,
            "request_id": getattr(request.state, "request_id", None),
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        """Chat completions endpoint.

        Non-streaming path: routing (Step 4) + real forward to backend (Step 5)
        with full header/auth rules.

        This step (6) adds basic observability: INFO logs at request start and
        completion (req_id, provider, models, latency, token counts when available).

        Streaming is still stubbed (real streaming + reconstruction in Phase 3).
        """
        req_id = getattr(request.state, "request_id", generate_request_id())
        logger = logging.getLogger(__name__)

        # Parse body once for routing decision (and to demonstrate the flow).
        # We stay very lenient because full request validation comes later.
        try:
            body = await request.json()
        except Exception:
            body = {}

        model = body.get("model", "default-model") if isinstance(body, dict) else "default-model"

        # Perform routing using the config that was attached by create_app()
        config = getattr(request.app.state, "config", None)
        if config is not None:
            from .routing import route_request

            provider, backend_model = route_request(model, dict(request.headers), config)
            # Safe observability log (no keys, no secrets)
            logger.info(
                "routing: client_model=%s -> provider=%s backend_model=%s (req_id=%s)",
                model,
                provider,
                backend_model,
                req_id,
            )
            routed_model = (
                f"{provider}/{backend_model}"
                if provider != config.default_provider
                else backend_model
            )
        else:
            provider, backend_model, routed_model = "lmstudio", model, model

        original_messages = body.get("messages", []) if isinstance(body, dict) else []
        client_model = model
        is_stream = bool(body.get("stream")) if isinstance(body, dict) else False

        # Basic start log (struct-ish, per DESIGN.md observability)
        logger.info(
            "request started: req_id=%s provider=%s client_model=%s backend_model=%s stream=%s",
            req_id,
            provider,
            client_model,
            backend_model,
            is_stream,
        )

        if not is_stream and config is not None:
            # Real non-stream forwarding (Step 5)
            send_body = (
                dict(body) if isinstance(body, dict) else {"model": backend_model, "messages": []}
            )
            send_body["model"] = backend_model

            from .forward import forward_request

            result = await forward_request(provider, send_body, config=config)

            # Completion log with timing and tokens (if backend provided usage)
            duration = result.get("duration_ms", 0.0)
            resp_json = result.get("json", {}) if isinstance(result.get("json"), dict) else {}
            usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
            logger.info(
                "request completed: req_id=%s provider=%s latency_ms=%.1f "
                "prompt_tokens=%s completion_tokens=%s total_tokens=%s status=%s",
                req_id,
                provider,
                duration,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                result.get("status_code"),
            )

            # === Core value: persist the conversation (Step 8/9) ===
            backend_json = resp_json
            assistant = None
            if isinstance(backend_json, dict):
                ch = (backend_json.get("choices") or [{}])[0]
                assistant = ch.get("message")
            record = {
                "request_id": req_id,
                "id": backend_json.get("id") if isinstance(backend_json, dict) else None,
                "timestamp": datetime.now().astimezone().isoformat(),
                "duration_ms": duration,
                "provider": provider,
                "client_model": client_model,
                "backend_model": backend_model,
                "streamed": False,
                "messages": original_messages,
                "assistant_message": assistant
                or {"role": "assistant", "content": None, "tool_calls": None, "refusal": None},
                "finish_reason": (backend_json.get("choices") or [{}])[0].get("finish_reason")
                if isinstance(backend_json, dict)
                else None,
                "usage": usage if usage else None,
                "extra": {"headers_snapshot": {}},
            }
            if not config.log_streams_only:
                try:
                    from .logging import log_interaction

                    log_interaction(
                        record,
                        log_dir=config.log_dir,
                        log_raw=config.log_raw,
                        raw_request=dict(body) if isinstance(body, dict) else None,
                        raw_response=backend_json if isinstance(backend_json, dict) else None,
                    )
                except Exception:
                    # Never let logging break the response to the client
                    logger.exception("message logging failed (non-fatal)")

            return JSONResponse(
                content=result["json"],
                status_code=result.get("status_code", 200),
                headers={"X-Request-ID": req_id},
            )

        # Streaming path (Step 7): live passthrough of SSE chunks + accumulation
        # for reconstruction. We now log the final reconstructed record in the
        # same format as non-stream (using on_done callback after client receives
        # all chunks).
        if is_stream and config is not None:
            from .streaming import event_stream

            # send_body already has the rewritten model from above
            send_body = (
                dict(body) if isinstance(body, dict) else {"model": backend_model, "messages": []}
            )
            send_body["model"] = backend_model
            # ensure stream flag
            send_body["stream"] = True

            chunks: list[dict] = []
            start_time = time.time()

            def on_stream_done():
                """Called after the client has received the full stream (incl. [DONE]).
                Build and log the record using the accumulated chunks + reconstruct.
                """
                end_time = time.time()
                duration = (end_time - start_time) * 1000.0
                if not chunks:
                    return
                try:
                    from .streaming import reconstruct_assistant_from_chunks
                    from .logging import log_interaction

                    assistant = reconstruct_assistant_from_chunks(chunks)

                    # Extract metadata from chunks (id, finish_reason, usage often in last chunks)
                    backend_id = None
                    finish_reason = None
                    usage = None
                    for c in reversed(chunks):
                        if isinstance(c, dict):
                            if not backend_id and c.get("id"):
                                backend_id = c.get("id")
                            if "choices" in c and c.get("choices"):
                                ch0 = c["choices"][0] if c["choices"] else {}
                                if ch0.get("finish_reason"):
                                    finish_reason = ch0.get("finish_reason")
                            if c.get("usage"):
                                usage = c.get("usage")
                            if backend_id and finish_reason and usage:
                                break

                    record = {
                        "request_id": req_id,
                        "id": backend_id,
                        "timestamp": datetime.now().astimezone().isoformat(),
                        "duration_ms": duration,
                        "provider": provider,
                        "client_model": client_model,
                        "backend_model": backend_model,
                        "streamed": True,
                        "messages": original_messages,
                        "assistant_message": assistant
                        or {"role": "assistant", "content": None, "tool_calls": None, "refusal": None},
                        "finish_reason": finish_reason,
                        "usage": usage,
                        "extra": {"headers_snapshot": {}},
                    }
                    log_interaction(
                        record,
                        log_dir=config.log_dir,
                        log_raw=config.log_raw,
                        raw_request=send_body,
                        raw_response=None,  # streaming raw is the chunks; main info is in the record
                    )
                except Exception:
                    # Never let logging break anything
                    logger.exception("message logging failed (non-fatal) for stream")

            # The event_stream yields the raw SSE lines (data: ... \n\n) with
            # zero modification for lowest latency. Accumulation + on_done for logging.
            return StreamingResponse(
                event_stream(provider, send_body, config, chunks=chunks, on_done=on_stream_done),
                media_type="text/event-stream",
                headers={"X-Request-ID": req_id},
            )

        # Fallback dummy (should rarely be hit now)
        created = int(time.time())
        payload = {
            "id": f"chatcmpl-dummy-{req_id[-8:]}",
            "object": "chat.completion",
            "created": created,
            "model": routed_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": (
                            "This is a fallback dummy response from tiny-llm-proxy (Step 7). "
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

        logger.info(
            "request completed (fallback dummy): req_id=%s provider=%s client_model=%s",
            req_id,
            provider,
            model,
        )

        return JSONResponse(
            content=payload,
            headers={"X-Request-ID": req_id},
        )

    # --- Additional endpoints (Step 10 polish) ---

    @app.get("/")
    async def root(request: Request) -> dict:
        cfg = getattr(request.app.state, "config", None)
        return {
            "name": "tiny-llm-proxy",
            "version": "0.1.0",
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
            "models": "/v1/models",
            "config": cfg.config_path if cfg else None,
        }

    @app.get("/v1/models")
    async def list_models(request: Request) -> JSONResponse:
        """Proxy GET /v1/models to the default (or configured) provider.

        Many clients (Continue.dev, Open WebUI, etc.) call this on startup.
        """
        cfg = getattr(request.app.state, "config", None)
        if cfg is None:
            return JSONResponse(
                content={"object": "list", "data": []},
                status_code=200,
                headers={"X-Request-ID": getattr(request.state, "request_id", "req_unknown")},
            )

        provider_name = cfg.default_provider
        try:
            provider = cfg.get_provider(provider_name)
        except KeyError:
            provider = next(iter(cfg.providers.values()))

        base = provider["base_url"].rstrip("/")
        # base_url should be the OpenAI-compatible base (e.g. https://openrouter.ai/api/v1 )
        # Append /models (not /v1/models)
        url = f"{base}/models"

        from .forward import prepare_backend_headers

        headers = prepare_backend_headers(provider)
        headers.pop("Content-Type", None)
        headers.pop("Accept", None)  # let backend decide, or set application/json

        verify_ssl = provider.get("verify_ssl", True)

        # Use a short-lived client for the models call (low frequency)
        import httpx as _httpx

        try:
            async with _httpx.AsyncClient(timeout=30.0, verify=verify_ssl) as c:
                r = await c.get(url, headers=headers)
            return JSONResponse(
                content=r.json()
                if r.headers.get("content-type", "").startswith("application/json")
                else {"data": []},
                status_code=r.status_code,
                headers={"X-Request-ID": getattr(request.state, "request_id", "req_unknown")},
            )
        except Exception as exc:
            return JSONResponse(
                content={"error": {"message": str(exc), "type": "proxy_error"}},
                status_code=502,
                headers={"X-Request-ID": getattr(request.state, "request_id", "req_unknown")},
            )

    return app


# Module-level app for:
# - `uvicorn tiny_llm_proxy.server:app` (no factory)
# - direct TestClient(app) usage in some tests
# - `python -m tiny_llm_proxy.server`
# It loads via the normal load_config() rules (usually the shipped example).
app = create_app()


# Convenience for `python -m tiny_llm_proxy.server` (uses the module-level app)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
