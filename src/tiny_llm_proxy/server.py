"""FastAPI application and endpoint definitions.

Step 3 (Phase 1): the server is now config-aware.
- create_app(config=...) builds an app using a loaded Config (providers, host/port, log_level etc.)
- GET /health and /v1/health now report the real configured provider names
- POST /v1/chat/completions still returns a dummy (non-stream) for this phase

Full routing (Step 4), forwarding (Phase 2), streaming + logging (Phase 3) come later.
Request ID middleware remains for observability.
"""

import time
from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
        """Dummy non-streaming chat completion endpoint (Phase 1).

        Routing (prefix + header) is now active and logged.
        Real provider forwarding, streaming reconstruction and persistent
        message logging are added in Phase 2/3.
        """
        req_id = getattr(request.state, "request_id", generate_request_id())

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
            import logging

            logging.getLogger(__name__).info(
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

        is_stream = bool(body.get("stream")) if isinstance(body, dict) else False

        if not is_stream and config is not None:
            # Real non-stream forwarding (Step 5)
            send_body = (
                dict(body) if isinstance(body, dict) else {"model": backend_model, "messages": []}
            )
            send_body["model"] = backend_model

            from .forward import forward_request

            result = await forward_request(provider, send_body, config=config)

            return JSONResponse(
                content=result["json"],
                status_code=result.get("status_code", 200),
                headers={"X-Request-ID": req_id},
            )

        # Streaming (or fallback): still dummy in this step
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
                            "This is a (still dummy for stream) response from tiny-llm-proxy (Step 5). "
                            "Non-stream calls are now forwarded to real backends. "
                            "Streaming + reconstruction + logging come later."
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 13,
                "total_tokens": 55,
            },
        }

        return JSONResponse(
            content=payload,
            headers={"X-Request-ID": req_id},
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
