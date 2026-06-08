"""FastAPI application and endpoint definitions.

Step 2 (Phase 0): minimal runnable server with:
- GET /health and /v1/health (returns stub providers)
- POST /v1/chat/completions (non-streaming dummy response only)

Real routing, config, forwarding, streaming, and logging arrive in later steps.
Request ID is threaded via middleware + header for observability.
"""

import contextlib
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .utils import generate_request_id

# Hardcoded for the dummy server (real values will come from config in Step 3+)
DUMMY_PROVIDERS = ["lmstudio"]


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request_id to every request (in state) and echo it in the response header."""

    async def dispatch(self, request: Request, call_next):
        req_id = generate_request_id()
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


app = FastAPI(
    title="tiny-llm-proxy",
    version="0.1.0",
    description="Tiny OpenAI-compatible proxy (step 2 dummy server)",
)


app.add_middleware(RequestIDMiddleware)


@app.get("/health")
@app.get("/v1/health")
async def health(request: Request) -> dict:
    """Simple health check. Includes the providers that would be loaded (stub for now)."""
    # In later steps this will reflect the real configured providers.
    return {
        "status": "ok",
        "providers": DUMMY_PROVIDERS,
        "request_id": getattr(request.state, "request_id", None),
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    """Dummy non-streaming chat completion endpoint.

    Accepts any OpenAI-shaped body (for now we ignore it).
    Always returns a valid OpenAI chat.completion JSON.

    Streaming support, real model forwarding, reconstruction, and logging
    are implemented in Phase 2/3.
    """
    req_id = getattr(request.state, "request_id", generate_request_id())

    # Consume the body so clients don't hang, but don't validate/parse yet.
    with contextlib.suppress(Exception):
        await request.json()  # dummy mode — be lenient

    created = int(time.time())

    # A minimal but valid OpenAI response shape.
    payload = {
        "id": f"chatcmpl-dummy-{req_id[-8:]}",
        "object": "chat.completion",
        "created": created,
        "model": "tiny-llm-proxy-dummy",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "This is a dummy response from tiny-llm-proxy (Phase 0 Step 2). "
                        "Real forwarding + streaming reconstruction + message logging "
                        "will be added in subsequent steps."
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


# Convenience for `uvicorn tiny_llm_proxy.server:app`
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
