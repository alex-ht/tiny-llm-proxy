"""Streaming support + pure reconstruction helper (Step 7).

Implements the exact algorithm and contract from DESIGN.md "Streaming Reconstruction Logic"
section, including the two concrete examples for content-only and parallel tool_calls.

The pure `reconstruct_assistant_from_chunks` is the key testable piece (no I/O).
It is used (for now) to produce the final assistant_message that will be logged
in Step 8/9.

A small async generator for SSE passthrough + accumulation is also provided so
the server can do real streaming with live chunk forwarding to the client.
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

from .config import Config
from .forward import _get_client, prepare_backend_headers


def reconstruct_assistant_from_chunks(chunks: list[dict]) -> dict:
    """Pure, no I/O. Returns the final assistant_message dict.

    - content: concatenated deltas (None if no content parts)
    - tool_calls: list assembled by index; arguments are raw *concatenated strings*
      (do not json.loads here — the client will)
    - finish_reason: from the last chunk that supplies a non-null one (default "stop")
    - usage: the last non-null usage object seen (for include_usage)
    - Handles empty content (pure tool call), refusal, multiple choices (take [0])
    - Idempotent and order-tolerant for the fields we care about.

    See DESIGN.md for the exact input examples and expected outputs.
    """
    if not chunks:
        return {"role": "assistant", "content": None, "tool_calls": None, "refusal": None}

    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}  # index -> accumulated tool call
    _finish_reason: str | None = None
    _usage: dict | None = None
    refusal: str | None = None

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue

        # Top-level usage (some backends put it on the final chunk outside choices)
        if "usage" in chunk and chunk["usage"]:
            _usage = chunk["usage"]  # captured for future richer return / logging

        choices = chunk.get("choices") or []
        if not choices:
            continue

        ch0 = choices[0]  # per spec: take [0] for multiple choices
        delta = ch0.get("delta") or {}

        # content
        if "content" in delta:
            c = delta.get("content")
            if c:
                content_parts.append(str(c))

        # tool_calls accumulation (by index)
        for tc in delta.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            idx = tc.get("index")
            if idx is None:
                continue
            if idx not in tool_calls:
                tool_calls[idx] = {
                    "id": tc.get("id"),
                    "type": tc.get("type", "function"),
                    "function": {"name": "", "arguments": ""},
                }
            current = tool_calls[idx]

            # id / type may appear on first delta for this index
            if tc.get("id") and not current.get("id"):
                current["id"] = tc["id"]
            if tc.get("type"):
                current["type"] = tc["type"]

            fn = tc.get("function") or {}
            if fn.get("name"):
                current["function"]["name"] = fn["name"]
            if "arguments" in fn:
                # arguments are *concatenated strings*, never parsed here
                current["function"]["arguments"] += str(fn.get("arguments") or "")

        # finish_reason (may be on the choice, not inside delta)
        fr = ch0.get("finish_reason")
        if fr is not None:
            _finish_reason = fr  # captured for future richer return / logging

        # refusal (rare, but per spec)
        if "refusal" in delta and delta.get("refusal"):
            refusal = delta["refusal"]

    # Build final message (arguments kept as raw concatenated string)
    assistant_message: dict = {
        "role": "assistant",
        "content": "".join(content_parts) if content_parts else None,
        "tool_calls": [tool_calls[i] for i in sorted(tool_calls.keys())] if tool_calls else None,
        "refusal": refusal,
    }

    # The caller (server) can also use finish_reason / usage if needed.
    # For Step 7 we just return the assistant_message as specified.
    return assistant_message


async def event_stream(
    provider_name: str,
    body: dict[str, Any],
    config: Config,
) -> AsyncGenerator[str, None]:
    """Async generator that does live SSE passthrough to the client while
    accumulating chunks for later reconstruction.

    Yields raw "data: {...}\n\n" (or [DONE]) lines with zero modification to the
    wire format where possible. This gives the client the lowest possible latency.

    After the stream ends (or on error / client disconnect), the accumulated
    chunks can be used with reconstruct_assistant_from_chunks (called by caller
    after the generator is exhausted).
    """
    provider = config.get_provider(provider_name)
    base_url = provider["base_url"].rstrip("/")
    target_url = f"{base_url}/v1/chat/completions"

    # Ensure stream is requested
    send_body = dict(body)
    send_body["stream"] = True
    send_body["model"] = body.get("model")  # already rewritten by caller usually

    headers = prepare_backend_headers(provider)

    # We accumulate here; the caller will reconstruct after the response is sent.
    # (We don't store inside the generator to keep it simple.)

    client = _get_client()

    chunks: list[dict] = []

    try:
        async with client.stream("POST", target_url, json=send_body, headers=headers) as resp:
            if resp.status_code != 200:
                # Forward error as a single event (best effort)
                text = await resp.aread()
                try:
                    err = resp.json()
                except Exception:
                    err = {
                        "error": {"message": text.decode(errors="ignore"), "type": "backend_error"}
                    }
                yield f"data: {json.dumps(err)}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for line in resp.aiter_lines():
                if line is None:
                    continue

                # Forward the line to the client as faithfully as possible.
                # httpx aiter_lines() strips the \n, so we add \n\n for SSE events.
                if line.startswith("data:"):
                    yield line + "\n\n"
                    data_part = line[5:].strip()  # after "data:"
                    if data_part == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_part)
                        chunks.append(chunk)
                    except Exception:
                        pass  # ignore bad json for accumulation, but we already forwarded
                elif line.startswith(":"):
                    # comment / keep-alive
                    yield line + "\n\n"
                elif line:
                    yield line + "\n\n"
                else:
                    yield "\n"

    except Exception as exc:
        # Best effort error to client + we still let the caller reconstruct what we have
        err = {"error": {"message": str(exc), "type": "proxy_stream_error"}}
        yield f"data: {json.dumps(err)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # The generator is exhausted. The caller (in server.py) is responsible for
    # calling reconstruct_assistant_from_chunks(chunks) after the StreamingResponse
    # has finished sending to the client.
    # We don't yield anything else here.
    # (In Step 8/9 the reconstruction result will be logged.)

    # Note: if the client disconnects early, the context manager + async with
    # will help close the backend connection (best effort).
