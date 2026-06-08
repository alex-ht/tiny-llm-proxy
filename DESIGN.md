# tiny-llm-proxy Design Document

**Project**: tiny-llm-proxy  
**Repository**: https://github.com/alex-ht/tiny-llm-proxy.git  
**Status**: Approved Design & Implementation Plan (v0.1 MVP)  
**Date**: 2026-06-08  
**Author**: Consolidated design (design doc + review feedback incorporated) for owner: AlexHT Hung  
**License**: MIT  
**Language**: English (technical) with notes for Traditional Chinese user-facing strings/examples where appropriate  
**Scope**: Authoritative guide for incremental implementation. This document is the single source of truth for the MVP.

---

> **Note**: This is the final consolidated design planning document. It incorporates all review feedback and clarifications. The original planning artifacts have been superseded by this file. Follow the PR Plan strictly for delivery.

## Overview

tiny-llm-proxy is a **very small, single-purpose** OpenAI-compatible proxy server. Its primary job is to sit between OpenAI-compatible clients (Continue.dev, Cursor, Open WebUI, custom `openai` SDK scripts, etc.) and one or more backend LLM servers that speak the OpenAI Chat Completions protocol.

The two mandatory backends for v1 are:
- **LM Studio** (local, `http://localhost:1234/v1`, usually no real API key).
- **OpenRouter** (`https://openrouter.ai/api/v1`, requires a real API key).

Future consideration (explicitly out of v1 core): local `llama-server` (from llama.cpp or llama-cpp-python) on its typical OpenAI-compatible port (often 8080 or 8000).

**The key value proposition** (and the reason for the project) is **reliable local persistence** of every conversation turn:
- The full `messages` array sent by the client.
- The assistant's generated response (reconstructed even for streaming).
- Essential metadata (model, provider used, timestamps, token usage if available, finish reason, duration, request id).

Logs are written to a user-configurable directory in a clean, **"message format"** (OpenAI `messages` style, easily convertible to ShareGPT or training datasets). No heavy frameworks, no database, no UI, no cloud — just a tiny Python process you point your clients at via `base_url`.

The entire project must remain **tiny**: small number of files, minimal dependencies, easy for a single developer to read, modify, and trust.

Current repository state (as of design time):
- Only `LICENSE` (MIT, Copyright 2026 AlexHT Hung) and standard Python `.gitignore`.
- Initialized git repo with remote `https://github.com/alex-ht/tiny-llm-proxy.git`.
- No source, no `pyproject.toml`, no `README.md`.

This document is the complete actionable guide for the first implementation.

---

## Background & Motivation

The owner (individual developer) regularly uses multiple LLM backends:
- Local models via LM Studio for privacy/speed/cost.
- OpenRouter for access to many frontier models with a single key and routing.
- Occasionally local `llama.cpp` servers.

All clients (editors, agents, web UIs) speak the OpenAI Chat Completions format. Manually switching `base_url` + keys per client or per session is annoying. More importantly, **there is no central record** of what was asked, what was answered, token counts, or full context for later review, debugging, dataset curation, or fine-tuning.

Existing solutions (LiteLLM proxy, etc.) are powerful but heavy — many features, complex config, larger dependency tree. The request is explicitly "**很簡單的**" (very simple) and "**tiny**".

Hence: a purpose-built, minimal proxy whose *only* extra feature beyond faithful forwarding (including streaming) is high-fidelity local logging of the conversation in message format.

---

## Goals & Non-Goals

### Goals (MVP / v1)
- Accept standard OpenAI `POST /v1/chat/completions` (and basic `GET /v1/models`).
- Forward **both streaming (`stream: true`)** and non-streaming requests faithfully to the selected backend, including all common parameters (`messages`, `tools`/`tool_calls`, vision/image content parts, `response_format`, `temperature`, `max_tokens`, `stream_options`, etc.).
- Reconstruct the final assistant message (content + tool_calls if present) from streaming deltas while still streaming live chunks to the client with minimal added latency.
- Persist every interaction to disk in a structured, queryable "message format" (see Data Model).
- Support at least two providers out of the box via simple configuration: `lmstudio` and `openrouter`. Easy to add `llamacpp` later.
- Allow routing choice per request via model-name prefix (e.g. `openrouter/gpt-4o`) **and/or** a custom header.
- Configuration primarily via a single YAML file + environment variables for secrets (keys). Never log secrets.
- Run as a simple local server (`uvicorn` or equivalent entrypoint) on `localhost` by default. Clients point `base_url` at the proxy (e.g. `http://localhost:8000/v1`).
- Console + structured logging for observability. Basic error passthrough in OpenAI error format.
- Minimal, understandable codebase (target: ~7-8 Python source files in practice, < 900 LOC application code for core; see "Tiny Scope Trade-offs" subsection for the deliberate FastAPI decision + measurement gate).
- Packaging with `pyproject.toml` + `uv` (modern, fast) + console script entrypoint.
- Clear `README` with copy-paste examples for LM Studio, OpenRouter, popular clients, and log inspection (using `jq`).

### Non-Goals (Explicitly Out of Scope for v1)
- No authentication / multi-user / multi-tenancy on the proxy itself (personal tool; run on localhost or behind your own reverse proxy if needed).
- No load balancing, failover, retries, or circuit breakers.
- No caching, prompt caching, or response caching.
- No prompt templating, system prompt injection, or guardrails.
- No cost tracking, token pricing, or usage dashboards.
- No built-in web UI or admin interface.
- No database (SQLite, Postgres, etc.); pure filesystem logs.
- No vector stores, RAG, or long-term memory.
- No advanced routing (A/B testing, latency-based, model fallbacks beyond simple config).
- No support for non-Chat endpoints initially (Completions legacy, Embeddings, Images, Audio, etc.) — only `/chat/completions` + minimal Models + health.
- No built-in dataset export scripts or fine-tuning pipelines (logs should be *easy* to consume for those, but not included).
- No Windows-specific service / systemd units (owner can add).
- No heavy deps (avoid pulling the full `openai` Python SDK into the proxy if possible; use direct `httpx`). The ASGI/web framework choice (FastAPI) is a documented, bounded exception with explicit rationale, file/LOC targets, and a final-step footprint check (see Tiny Scope Trade-offs).
- No persistent sessions or conversation threading inside the proxy (clients already manage the `messages` array).

Future versions (post-v1, only if requested) may add narrow features from the non-goals list, but the spirit must remain "tiny".

### Tiny Scope Trade-offs (explicit resolution of "very simple" vs. implementation practicality)

The design targets a *personally maintained* tool used primarily on the owner's dev machine. After weighing:

- **Recommendation (architect decision)**: Keep **FastAPI + uvicorn[standard] + httpx + pyyaml** as the primary stack (with the note in Proposed Design that `models.py` may be omitted entirely in favor of `dict` + `TypedDict` or minimal Pydantic for the log record only). FastAPI provides:
  - Zero-boilerplate request/response models and validation for the chat endpoint (reduces bugs in a streaming proxy).
  - Auto-generated `/docs` (OpenAPI) invaluable while iterating on exact request shapes, streaming, and error formats.
  - Mature StreamingResponse + dependency system for threading request_id cleanly.
  - The transitive footprint (pydantic, starlette, etc.) is ~10-15 MB installed and well-understood; it is *not* LiteLLM-scale.

- **File / LOC discipline**: Target **7-8 core runtime Python files** in practice (combine `main.py` + `server.py` entry if desired; drop or keep `models.py` as a 20-line stub). Core implementation (excluding tests/docs) aim for **< 900 LOC** of application code (measured by `wc -l src/tiny_llm_proxy/*.py` excluding blanks/comments). The 11-entry tree in the design is the "full picture" including optional; the implementer should consolidate aggressively.

- **Acceptance gate in final step**: In the PR for step 12 (or as a manual checklist item after `uv pip install -e .`), run and record:
  ```
  python -c "import tiny_llm_proxy; print('import ok')"
  uv pip install -e . --no-deps 2>&1 | tail -5   # or pip show -f
  wc -l src/tiny_llm_proxy/*.py
  ```
  If the numbers feel too heavy for the owner's taste, a follow-up "tiny stack" spike (pure Starlette + manual ASGI + anyio) can be a v0.2 experiment without blocking v1 logging value. This decision prioritizes speed-to-usable-MVP and correctness of the hard parts (streaming reconstruction + faithful forwarding + clean logs) over shaving every last dependency for a personal tool.

This subsection, the updated Key Decisions below, the tightened file list, and the footprint gate in the PR Plan directly address feasibility concerns while preserving the "tiny" spirit (no god modules, direct httpx, no openai SDK, pure FS logs, narrow feature set).

---

## Proposed Design

### High-Level Architecture

```mermaid
graph TD
    Client["Client<br/>(Continue.dev / Cursor /<br/>openai SDK / Open WebUI)"] 
    -->|base_url=http://localhost:8000/v1<br/>+ optional X-Provider or model prefix| Proxy

    subgraph Proxy ["tiny-llm-proxy (FastAPI + uvicorn)"]
        Router[Routing Logic<br/>prefix map + header]
        Forwarder[Request Forwarder<br/>(httpx async)]
        Reconstructor[Streaming Reconstructor<br/>(accumulate deltas)]
        Logger[Message Logger<br/>(JSONL writer)]
        Config[Config Loader<br/>(YAML + env)]
    end

    Proxy -->|selected backend| LMStudio["LM Studio<br/>http://localhost:1234/v1<br/>(no/dummy key)"]
    Proxy -->|selected backend + key| OpenRouter["OpenRouter<br/>https://openrouter.ai/api/v1<br/>(real key)"]
    Proxy -.->|future| LlamaCPP["llama.cpp server<br/>http://localhost:8080/v1<br/>(sk-no-key-required)"]

    LMStudio & OpenRouter & LlamaCPP -->|SSE chunks or full JSON| Forwarder
    Forwarder --> Reconstructor
    Reconstructor -->|live chunks| Client
    Reconstructor -->|final assembled assistant msg + meta| Logger
    Logger -->|append| LogDir["logs/<YYYY-MM-DD>/<date>.jsonl<br/>(or configurable)"]

    Config --> Router
    Config --> Forwarder
```

**Key components (proposed files under `src/tiny_llm_proxy/`)**:
- `config.py`: Load YAML, resolve env vars for keys, validate providers, build routing map.
- `routing.py`: Decide backend from request (model prefix or header `X-TinyLLM-Provider` / `X-Provider`).
- `proxy.py` or `server.py`: FastAPI app, `/v1/chat/completions` endpoint (streaming + non), error handling, `/v1/models`, health.
- `forward.py`: Async forwarding logic using `httpx.AsyncClient`; handles auth injection per provider.
- `streaming.py`: SSE parsing + delta accumulation for content + tool_calls; produces final message for logging while yielding chunks.
- `logging.py`: The "message logger" — redacts secrets, writes normalized interaction record to JSONL.
- `models.py`: Pydantic models for request/response sanitization (lightweight; or use `typing` + dicts to stay tinier).
- `main.py` / `__main__.py`: Entry point, uvicorn launch, startup logging of loaded providers + log dir.
- `utils.py`: ID generation, timestamping, duration, header sanitization.

**Dependencies (minimal)**: `httpx`, `pyyaml`, `uvicorn[standard]`, `fastapi` (or `starlette` + `pydantic` if wanting to trim; FastAPI recommended for clarity and auto-docs during dev). Optional: `python-dotenv` for `.env` loading. No `openai` package in the proxy itself.

### Request Flow (Sequence Diagram)

```mermaid
sequenceDiagram
    participant C as Client
    participant P as Proxy (tiny-llm-proxy)
    participant B as Backend (LM / OR)
    participant L as Logger (disk)

    C->>P: POST /v1/chat/completions<br/>{model: "openrouter/...", messages: [...], stream: true, ...}<br/>+ headers (incl. optional X-Provider)
    P->>P: Load config + select provider (prefix or header)
    P->>P: Redact client headers for logging; prepare backend headers + key
    alt Non-streaming
        P->>B: POST /v1/chat/completions (full body, rewritten model)
        B-->>P: 200 JSON {choices[0].message, usage, ...}
        P->>P: Assemble final assistant message
        P->>L: Write interaction record (messages + assistant + meta)
        P-->>C: 200 JSON (passthrough or lightly normalized)
    else Streaming
        P->>B: POST /v1/chat/completions (stream=true)
        loop SSE chunks from B
            B-->>P: data: {"choices":[{"delta":{"content":"..."}}], ...}
            P->>P: Accumulate deltas (content + tool_calls)
            P-->>C: data: <chunk> (forward immediately)
        end
        P->>P: On [DONE] or last usage chunk: finalize assistant_message
        P->>L: Write interaction record (reconstructed)
        P-->>C: data: [DONE]
    end
    Note over P,L: All writes are append-only; keys never written
```

Streaming reconstruction is critical: the client sees low-latency tokens exactly as the backend sends them. The proxy only buffers what is necessary to build the final `assistant_message` object for the log record.

---

## API / Interface

### Mandatory (v1)
- `POST /v1/chat/completions`
  - Full fidelity for the common surface: `messages` (text + vision parts + tool results), `tools` / `tool_choice`, `stream` + `stream_options`, `response_format`, usage-related fields, `temperature`, `top_p`, `max_tokens`/`max_completion_tokens`, `stop`, `seed`, `frequency_penalty`, etc.
  - The proxy **must not** drop or alter fields it doesn't understand — forward the JSON body (with only `model` possibly rewritten and auth headers injected).
  - Response: exact backend response shape (or minimal normalization to be valid OpenAI). For streaming, pure passthrough of `data:` lines + `[DONE]`.
- `GET /health` or `GET /v1/health` (simple `{"status":"ok"}` + loaded providers).
- `GET /v1/models` (nice-to-have but strongly recommended for v1): Proxy to the **default** provider's `/v1/models` (or merge from configured providers if cheap). Many clients (Continue, Open WebUI) call this on startup.

### Nice-to-Have (still v1 if easy)
- `GET /` or root redirect to health + short info.
- Basic CORS if needed for browser clients (but prefer running locally).
- Request ID propagation (`X-Request-ID`).

### Out of Scope for v1 Endpoints
- `/v1/completions` (legacy), embeddings, images, audio, assistants, etc.
- Any non-OpenAI paths.

**Client usage example** (Python):
```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:8000/v1",  # point at proxy
    api_key="dummy-or-proxy-key-if-added-later",  # often ignored for local
)
resp = client.chat.completions.create(
    model="openrouter/openai/gpt-4o",  # routing via prefix
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)
```

For LM Studio: `model="lmstudio/llama-3.2-3b"` or just the local model name if default provider is lmstudio.

**Header-based routing** (alternative or override):
```
X-TinyLLM-Provider: openrouter
# or X-Provider: openrouter
```
Model can then be the raw backend model name.

### Configuration Interface (see later section)

---

## Data Model (for Logs)

### Directory Layout (concrete)
```
<log_dir>/                  # default: ./logs  or  ~/.local/share/tiny-llm-proxy/logs
  2026-06-07/
    interactions-2026-06-07.jsonl
  2026-06-08/
    interactions-2026-06-08.jsonl
  ...
  raw/                      # optional, only if debug_raw: true (redacted)
    2026-06-07/
      chatcmpl-abc123.req.json   # sanitized request
      chatcmpl-abc123.resp.json  # full backend response (keys stripped)
```

Rationale for date-partitioned daily JSONL:
- Append-only, atomic line writes (easy `echo '...' >> file` or `json.dump` + `\n`).
- Natural partitioning for time-based queries.
- One file per day keeps sizes manageable; `jq` / `grep` / Python one-liners are fast.
- Alternative (considered): one giant `all.jsonl` or per-conversation directories — rejected for v1 because proxy has no conversation ID concept and per-request is simplest.

File naming: `interactions-YYYY-MM-DD.jsonl` (or `requests-...`).

### Interaction Record (exact proposed JSON shape per line)

Each line in the JSONL is one self-contained object:

```json
{
  "request_id": "req_01hxyz123abc",
  "id": "chatcmpl-9abc123def456",
  "timestamp": "2026-06-07T14:22:33.456789+08:00",
  "duration_ms": 1247,
  "provider": "openrouter",
  "client_model": "openrouter/openai/gpt-4o-mini",
  "backend_model": "openai/gpt-4o-mini",
  "streamed": true,
  "messages": [
    {"role": "system", "content": "你是一個有幫助的助手。"},
    {"role": "user", "content": "請用繁體中文解釋代理伺服器的好處。"}
  ],
  "assistant_message": {
    "role": "assistant",
    "content": "代理伺服器可以統一存取多個後端 LLM 服務，並且自動記錄所有對話內容...",
    "tool_calls": null,
    "refusal": null
  },
  "finish_reason": "stop",
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 128,
    "total_tokens": 170
  },
  "extra": {
    "finish_reason_details": null,
    "headers_snapshot": {
      "user-agent": "openai-python/1.XX",
      "x-tinyllm-provider": "openrouter"
    }
  }
}
```

**Notes on the format**:
- `"messages"`: exact copy of the client's `messages` array (after any minimal sanitization). This is the "message format" the user requested — directly usable for ShareGPT conversion or training (many tools accept OpenAI messages format natively; see torchtune, etc.).
- `"assistant_message"`: the **final** reconstructed message from the response (or last deltas). For tool calls, the full `tool_calls` array goes here.
- `"usage"`: from the non-stream response or the final usage chunk (when client sends `stream_options: {"include_usage": true}`).
- Vision: if a message part is `{"type": "image_url", "image_url": {...}}`, it is preserved verbatim in `messages`. (Logs will contain base64 or URLs — user responsibility.)
- `request_id`: Proxy-generated (or propagated from `X-Request-ID` header if present). Always present; used to correlate conversation logs with console/observability logs and error traces. Generated in `utils.py` early in request handling and threaded through.
- `id`: Prefer the backend's `id` (e.g. `chatcmpl-...`); fall back to a generated UUIDv4 or `proxy-<ts>-<rand>`.
- `timestamp`: ISO8601 with local offset or UTC (document choice; recommend local for personal logs).
- `extra`: lightweight — only safe, useful metadata. Never include Authorization or keys.
- For non-stream: same shape.
- Tool use / parallel tools: the full `tool_calls` list + any `content` is captured; subsequent `tool` role messages will appear in the *next* request's `messages` array (as the client appends them).

**"Message format" usability**: To turn a log line into a clean training example:
```bash
jq -r '.messages + [.assistant_message] | {messages: .}' interactions-*.jsonl > training.jsonl
```
Or convert to ShareGPT `conversations` with a one-liner script (out of scope for core but trivial for owner).

**Raw logging (optional, behind `log_raw: true` in config, default false)**: Store full request body (sanitized) and full backend response in a `raw/` tree. Useful for deep debugging of tool calls or vision. Keys and sensitive headers are stripped before writing.

---

## Configuration Approach

Primary: `config.yaml` (or `config.yml`) next to the process or at a path given by `--config` / `TINYLLM_CONFIG` env var.

Example `config.example.yaml` (shipped in repo):

```yaml
# tiny-llm-proxy configuration
# Authoritative top-level keys for v1 simplicity (server.* for bind only; no nested log_level).
server:
  host: "127.0.0.1"
  port: 8000

logging:
  level: "info"            # controls stdlib logging + uvicorn where possible; also exposed as top-level for backward compat in loader
  # json: false

log_dir: "./logs"          # or "~/.local/share/tiny-llm-proxy/logs"
log_raw: false             # write full request/response bodies (redacted) for debug

default_provider: "lmstudio"

providers:
  lmstudio:
    base_url: "http://localhost:1234/v1"
    api_key: null          # or "" ; LM Studio usually accepts anything or nothing
    # extra_headers: {}

  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    # api_key: "sk-or-..."   # NEVER commit real keys; use env below
    api_key_env: "OPENROUTER_API_KEY"
    extra_headers:
      HTTP-Referer: "https://github.com/alex-ht/tiny-llm-proxy"
      X-OpenRouter-Title: "tiny-llm-proxy"

  # Example for future llama.cpp (user can uncomment + configure)
  # llamacpp:
  #   base_url: "http://localhost:8080/v1"
  #   api_key: "sk-no-key-required"
  #   api_key_env: "LLAMACPP_API_KEY"   # optional

routing:
  # Model prefix -> provider name
  prefix_map:
    "lmstudio/": "lmstudio"
    "openrouter/": "openrouter"
    "or/": "openrouter"
    "llamacpp/": "llamacpp"
    "local/": "lmstudio"   # convenience

  # Also accept these request headers (case-insensitive match in code)
  header_names: ["X-TinyLLM-Provider", "X-Provider", "X-LLM-Provider"]

  # If no routing info, fall back to default_provider
```

**Secrets handling**:
- Real keys live **only** in environment variables or (temporarily) in the YAML for local testing.
- At load time, `api_key_env` is resolved; if both `api_key` (literal) and env are present, env wins or errors (document policy).
- The resolved key is injected **only** into the `Authorization: Bearer ...` header sent to the backend. It is **never** stored in the config object after startup for logging, and **never** written to disk logs.
- Support for per-request key passthrough for OpenRouter-style providers (advanced, nice-to-have): if client sends a header like `X-OpenRouter-Key` or the proxy sees a special model, forward it. For v1 keep simple — keys are configured.

**Env var overrides** (optional but nice): `TINYLLM_LOG_DIR`, `TINYLLM_DEFAULT_PROVIDER`, etc. Can be implemented with a small env overlay on the loaded dict.

**Loading library**: `pyyaml` + a small recursive `${VAR}` or `$VAR` expander (common pattern; ~20 lines). No pydantic-settings required for v1 (keeps deps lower), but Pydantic models for runtime validation of the loaded config is fine.

**Config schema note (for implementer in step 3)**: Use a flat-ish structure with `server:`, `logging:`, `providers:`, `routing:` as top-level sections. `log_level` / `logging.level` is the single source for verbosity (top-level `log_level` accepted for loader compatibility if present). The runtime Config object should expose `log_level`, `log_dir`, `log_raw`, `default_provider`, `providers` dict, `routing` rules. Startup banner and uvicorn log config derive from these.

**Header & Auth Construction Rules** (exact logic for `forward.py` + `config.py`, also referenced from Security & Privacy and step 5):
- Never forward any incoming client `Authorization` (or `X-*-Key` / `api-key` style) header to the backend unless a future per-provider passthrough flag is explicitly enabled (v1: always strip for security and to avoid surprising local servers).
- Only emit an `Authorization: Bearer <key>` header to the backend when the resolved key for the selected provider (after `api_key_env` lookup + literal fallback) is a non-empty string. If `api_key` is `null` or `""` (as for `lmstudio`), omit the header entirely.
- For local providers that are picky about presence of Authorization (LM Studio, llama.cpp server): document and default to "omit". If a backend requires a specific dummy, the user sets `api_key: "sk-no-key-required"` (or equivalent) in the provider config — the proxy will then send it.
- Always apply redaction (case-insensitive match on header names containing "auth", "key", "token", "authorization", or values starting with "sk-"/"Bearer ") before writing any request snapshot to `extra.headers_snapshot` or to raw/ logs.
- OpenRouter-specific extra headers from config (Referer etc.) are always added when the provider is selected; they are safe and useful.
- In client usage docs (final README): for pure LM Studio use with default provider, no `api_key` is required on the proxy client (the OpenAI SDK `api_key` param can be any dummy string; it is ignored by the proxy for local providers).

---

## Streaming Reconstruction Logic

This is one of the more subtle parts and must be implemented carefully.

1. Client sends `stream: true`.
2. Proxy forwards the request with `stream: true` (and `stream_options` if present).
3. Backend responds with `text/event-stream`.
4. Proxy reads the stream line-by-line (or chunk-by-chunk).
5. For every `data: {...}` line:
   - If it is `[DONE]`, finalize and forward.
   - Parse the JSON chunk.
   - Immediately forward the original `data: <original json>\n\n` (or the whole line) to the client — zero modification to the wire format if possible.
   - Inspect `choices[0].delta`:
     - Accumulate `delta.get("content", "")` into a buffer string.
     - For tool_calls: accumulate by index (OpenAI streams partial `function.arguments` strings and `id`/`name` on first appearance). Maintain a map of index -> partial tool call.
     - Also capture `usage` if present on the final chunk (when `include_usage`).
6. On stream end: build the final `assistant_message`:
   ```python
   assistant_message = {
       "role": "assistant",
       "content": content_buffer or None,
       "tool_calls": [completed_tool_call_objects] or None,
       ...
   }
   ```
7. Write the log record **after** the stream to client has completed (or fire-and-forget in background thread/task if latency sensitive — but keep simple: after).
8. Edge cases: empty content (tool-only calls), refusal, multiple choices (rare; log first choice), error chunks (log the error, forward it).

**Concrete reconstruction examples and pure helper contract** (add to `streaming.py` + `tests/test_streaming.py` before step 7; makes the "unit-testable pure functions" immediately actionable):

1. Content-only (typical text stream, last chunk carries finish_reason + optional usage):
   Input chunks (simplified deltas):
   - `{"choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": null}]}`
   - `{"choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": null}]}`
   - `{"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}`  (when `include_usage` used)
   Expected `assistant_message`:
   ```json
   {"role": "assistant", "content": "Hello world", "tool_calls": null, "refusal": null}
   ```
   `finish_reason` from the chunk that has it (or last non-null); `usage` captured if present on any chunk.

2. Tool calls (parallel possible; name/id appear on first delta for that index; arguments are *concatenated strings* — never parse until the end):
   Input chunks:
   - `{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_123", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}, "finish_reason": null}]}`
   - `{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"city\":"}}]}, "finish_reason": null}]}`
   - `{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"Paris\"}"}}]}, "finish_reason": null}]}`
   - `{"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}`
   Expected `assistant_message` (arguments kept as the *full concatenated string* per OpenAI contract; client will parse JSON):
   ```json
   {
     "role": "assistant",
     "content": null,
     "tool_calls": [
       {
         "id": "call_123",
         "type": "function",
         "function": {"name": "get_weather", "arguments": "{\"city\":\"Paris\"}"}
       }
     ],
     "refusal": null
   }
   ```

Pure helper signature and behavior (implement first, test-driven):
```python
def reconstruct_assistant_from_chunks(chunks: list[dict]) -> dict:
    """Pure, no I/O. Returns the final assistant_message dict + side outputs if needed.
    - content: concatenated deltas.
    - tool_calls: list assembled by index; arguments are raw concatenated strings (do not json.loads here).
    - finish_reason: from the last chunk that supplies a non-null one (or "stop" default).
    - usage: the last non-null usage object seen (for include_usage case).
    - Handles empty content (pure tool call), refusal, refusal deltas, multiple choices (take [0]).
    - Idempotent and order-tolerant for the fields we care about.
    """
    ...
    return assistant_message  # plus optionally (finish_reason, usage) tuple for caller
```
The streaming path calls this at end-of-stream (or on error) to produce the value for the interaction record. Non-stream path bypasses it. Edge cases (tool_calls + content mixed, zero chunks, error mid-stream) must be covered by the unit tests for this helper.

Non-streaming path is trivial: take `choices[0].message` directly.

---

## Error Handling, Logging (Observability), and Resilience

- **Errors from backend**: Forward the exact status code and JSON body (OpenAI error shape: `{"error": {"message": "...", "type": "...", "code": "..."}}`). Log at ERROR level with request id + provider.
- **Proxy errors** (bad config, routing failure, client disconnect mid-stream): Return appropriate 4xx/5xx in OpenAI-ish format. Never leak stack traces to client in production mode.
- **Client disconnect**: Best-effort — try to close backend connection; still attempt to log what was received so far (partial assistant message is valuable).
- **Structured logging (console + optional file)**:
  - Use `logging` stdlib or a tiny wrapper. Emit JSON lines on a separate handler if `log_json: true`.
  - Example line: `{"ts": "...", "level": "INFO", "req_id": "...", "provider": "openrouter", "model": "...", "stream": true, "latency_ms": 1234, "prompt_tokens": 42, "completion_tokens": 87, "msg": "request completed"}`
  - Separate from the *conversation* message logs.
- **Startup banner**: Print loaded providers (names + base_urls, **never keys**), log directory, routing map summary.
- **No retries** in v1 (explicit non-goal). If backend is down, client sees the error.
- **Timeouts**: Reasonable defaults on httpx client (e.g. 300s for long generations); configurable per-provider later.

---

## Security & Privacy

- **API Keys**:
  - Never appear in logs, never in Git, never in process listings if possible.
  - Loaded once at startup into memory only for the `Authorization` header construction.
  - Redaction function: any header containing `auth`, `key`, `token`, `authorization` (case-insensitive) is replaced by `[REDACTED]` before any logging or raw storage.
- **Logged data**:
  - Contains the **full conversation** the user had with the model (including any system prompts, tool results, vision descriptions or image URLs/base64 if sent).
  - This can include private code, personal information, secrets the user accidentally pasted, etc.
  - **User responsibility**: Protect the `log_dir`. Consider permissions (`chmod 700`), encryption at rest if on shared machine, or excluding the logs dir from backups/cloud sync.
  - The design provides no automatic PII scrubbing.
- **Network**:
  - Default bind `127.0.0.1` only. Do not expose publicly without adding auth (out of scope v1).
  - For OpenRouter, the proxy adds the required `HTTP-Referer` / title headers from config (good for attribution).
- **Proxy-level auth (future)**: A simple bearer token checked on incoming requests can be added later via config + header check. Not in MVP.
- **Vision / large content**: Logs can become large (base64 images). Owner should monitor disk usage.

---

## Observability (Beyond Conversation Logs)

- Console output on every request (or at info level: start + end with summary stats).
- Per-request timing (total duration; optionally time-to-first-token for streams — nice-to-have).
- Easy to add Prometheus `/metrics` later (out of scope) because the core is small.
- Request IDs: generate or propagate one; include in all log lines (conversation log + access log).
- Health endpoint can surface "last error" or simple counters in memory (ephemeral).

---

## Project Structure & Packaging

Proposed after initial implementation steps:

```
tiny-llm-proxy/            # example layout after `git clone` (or ~/.../tiny-llm-proxy/)
├── LICENSE                 # existing
├── .gitignore              # existing + additions (logs/, .env, *.log, config.local.yaml, __pycache__, .ruff_cache, dist/, etc.)
├── pyproject.toml          # [project], dependencies, [project.scripts], [tool.uv], ruff/black config, etc.
├── README.md               # comprehensive usage, config example, client snippets (incl. Continue.dev baseUrl + extra headers), log querying examples
├── config.example.yaml     # safe template with comments
├── src/
│   └── tiny_llm_proxy/
│       ├── __init__.py
│       ├── __main__.py     # python -m tiny_llm_proxy
│       ├── main.py         # uvicorn entry, app factory
│       ├── config.py
│       ├── routing.py
│       ├── server.py       # FastAPI app + endpoints
│       ├── forward.py
│       ├── streaming.py
│       ├── logging.py      # conversation logger (distinct from std logging)
│       ├── models.py       # optional Pydantic or TypedDicts
│       └── utils.py
├── tests/                  # minimal (test_config, test_routing, test_streaming_reconstruct) — scaffolded early
│   └── ...
└── .github/
    └── workflows/
        └── ci.yml          # basic lint + pytest (scaffolded early)
```

**Packaging decisions**:
- Use `uv` (already present on the machine) for development and building. `pyproject.toml` with `uv` lockfile (can be committed or not — document).
- Console script: `tiny-llm-proxy` → runs the server.
- Also support `python -m tiny_llm_proxy`.
- Version: start at `0.1.0`; single source of truth in `pyproject.toml` + `__version__`.
- Extras: none for v1.
- Python requires: `>=3.10` (matches the dev machine).

**Development**:
- `uv sync`
- `uv run tiny-llm-proxy --config config.example.yaml`
- Or `uv run uvicorn tiny_llm_proxy.server:app --reload`

---

## Alternatives Considered

### Routing Strategy
**Option A (chosen primary)**: Model name prefix map (e.g. `openrouter/...`) + fallback to explicit headers (`X-TinyLLM-Provider`) + default provider.
- Pros: Works out-of-the-box with most clients (just change the `model` string); explicit header is escape hatch; very little client change needed.
- Cons: Prefixes pollute the model namespace slightly; requires maintaining a map.
- **Rationale for choice**: Best ergonomics for the target users (personal developer switching between local and cloud often). Prefixes are the convention used by LiteLLM and many routers.

**Option B**: Header-only (`X-Provider`).
- Pros: Clean model names.
- Cons: Every client integration must be taught to send the extra header (SDKs support `default_headers` or `extra_headers` per call, but it's friction).

**Option C**: Separate proxy instances per provider (e.g. run two processes on different ports).
- Rejected: defeats the "one place to point all clients + one log dir" goal.

**Hybrid (implemented)**: Prefix is the happy path; header always wins if present for overrides.

### Logging Format & Storage
**Option A (chosen)**: Daily JSONL files with OpenAI-style `messages` + `assistant_message` + rich metadata. Optional redacted raw siblings.
- Pros: Append-friendly, great for `jq` / line-based processing, directly "message format" for datasets, human readable per line, easy date-based retention.
- Cons: Not a single file; large individual lines if vision payloads.

**Option B**: Individual `.json` files per interaction (`logs/2026-06-07/chatcmpl-xxx.json`).
- Pros: Easy to `ls` and inspect one.
- Cons: Thousands of small files; slower for bulk processing; directory bloat.

**Option C**: Full raw request + raw response only (no normalization).
- Rejected for primary path: hard to use for training data; contains noise (ids, timestamps internal to backend); still need to reconstruct assistant for "the conversation".

**Option D**: ShareGPT `conversations` as primary.
- Close second. We chose OpenAI `messages` because it is what the wire format already uses, and conversion to ShareGPT is trivial (`role`/`content` → `from`/`value` with mapping `assistant`→`gpt`, `user`→`human`). Document the conversion in README.

**Option E**: SQLite or DuckDB for logs.
- Rejected: adds dep + complexity; "very simple" and "output to specific directory" points to plain files. JSONL is the sweet spot between DB and raw files.

### Other Notable
- Using the official `openai` Python package inside the proxy for forwarding vs raw `httpx`: raw `httpx` wins for size, control, and avoiding SDK version coupling.
- FastAPI vs pure Starlette + manual routing: FastAPI selected (with full rationale, ~7-8 file target, and footprint acceptance gate documented in the new "Tiny Scope Trade-offs" subsection and Key Decisions). The decision favors implementation speed and correctness for the non-trivial streaming + logging core over absolute minimalism for this personal-tool scope. A pure-Starlette spike remains possible post-v1 if measured size feels excessive.
- YAML vs TOML vs pure env: YAML wins for readability of lists/maps of providers + comments. Env for secrets only.

---

## Key Decisions

1. **Model-prefix routing (with header override) is the primary mechanism, defaulting to a configurable provider.**  
   Rationale: Maximizes compatibility with existing clients that only let you change `model` and `base_url`. Header provides power users an escape hatch without forcing every integration to use headers.

2. **Conversation logs are written as one JSON object per `/chat/completions` request (per turn), using OpenAI `messages` + reconstructed `assistant_message`.**  
   Rationale: Matches the user's explicit request for "message format". This shape is immediately useful for inspection, scripting, and conversion to training datasets (ShareGPT, torchtune chat format, etc.). Per-request is the only state the stateless proxy has.

3. **Daily partitioned JSONL (`logs/YYYY-MM-DD/interactions-YYYY-MM-DD.jsonl`)** as the default on-disk format, with optional redacted raw.  
   Rationale: Append-only, tooling-friendly (`jq`, `tail -f`, simple Python scripts), natural retention by date, avoids millions of tiny files or one enormous file.

4. **Streaming is first-class: live passthrough of every chunk to the client, with parallel delta accumulation only for the final log record.**  
   Rationale: Users (especially in editors) are latency-sensitive. The logging value must not degrade the interactive experience.

5. **No dependency on the `openai` Python SDK in the proxy.** Direct `httpx` + manual (de)serialization. FastAPI/uvicorn chosen for the ASGI layer (see the dedicated "Tiny Scope Trade-offs" subsection for the explicit rationale, footprint targets, and acceptance gate).  
   Rationale: Keeps the installed size tiny *relative to the value*, avoids SDK bloat..., while FastAPI's DX justifies the (well-bounded) transitive deps for rapid correct implementation of streaming + routing + logging on a greenfield personal project.

6. **Configuration is a single human-readable `config.yaml` + environment variables for all secrets.**  
   Rationale: Easy to version-control the structure (example file), while keys stay out of git. Matches "simple" requirement.

7. **Logs contain the *full* conversation content (including vision payloads if present) but *never* API keys or sensitive auth material.**  
   Rationale: Fidelity for the use cases (debug, dataset creation). Privacy is the *user's* duty via filesystem controls and log_dir placement. The proxy makes redaction of its own secrets automatic and reliable.

8. **Support `/v1/models` by proxying the default (or a designated) provider's models endpoint.**  
   Rationale: Many popular clients call it at startup to populate model pickers. Low cost to implement, high usability win.

9. **Keep the entire implementation under a handful of focused modules with clear separation (config, routing, forward, streaming, logging).** In practice consolidate to ~7-8 files (see Tiny Scope Trade-offs and the updated project tree).  
   Rationale: "Tiny" means a new contributor (or future self) can understand the whole system in <30 minutes. Avoid god modules. The explicit stack + file-count decision + footprint gate in PR Plan step 12 makes the target measurable rather than aspirational.

10. **MVP ships with exactly the two confirmed providers (lmstudio + openrouter) + clear extension points for llamacpp and others.**  
    Rationale: Delivers on the stated requirements without speculative code. Adding a third provider later should be a 10-20 line change + config entry.

---

## PR Plan (Implementation Phases)

All steps are ordered for incremental progress. Each step should produce a working (or testable) increment that can be merged independently where possible. Since this is a brand-new project, early steps focus on scaffolding + docs that unblock everything else.

**Phase 0: Foundation (Setup)**
1. **Repo hygiene + packaging skeleton**  
   Affected files/components: `pyproject.toml` (new), `README.md` (new), update `.gitignore`, `config.example.yaml` (new), `src/tiny_llm_proxy/__init__.py` + `__version__`, `LICENSE` (already present).  
   Description: Define project metadata, dependencies (httpx, pyyaml, uvicorn[standard], fastapi), console script `tiny-llm-proxy`, Python >=3.10, ruff/black config, src layout. Add logs/ and .env patterns to gitignore. Create *minimal* README with high-level "what it is" + quickstart (once implemented); do not embed the full design here (reference `DESIGN.md` at repo root for complete spec, data models, config examples, and the PR Plan). Detailed execution steps and decisions are captured in PR descriptions and commit messages. Include example config stub. `uv sync` should work.
   Also in this step: scaffold `tests/` (with `conftest.py`, a trivial `test_health.py` that can run against the future dummy server, `pyproject.toml` `[tool.pytest.ini_options]` + ruff config), and a minimal `.github/workflows/ci.yml` (runs `ruff check`, `ruff format --check`, `pytest` on push/PR even while early steps only have dummy endpoints). This ensures every subsequent PR (config, routing, etc.) lands with automated checks from the start.  
   Dependencies: None (first step).  
   Mergeable: Yes — pure setup.

2. **Basic runnable server with health and dummy chat endpoint**  
   Affected: `src/tiny_llm_proxy/main.py`, `server.py` (or combined), `utils.py`.  
   Description: `uvicorn` launchable app. `GET /health` returns `{"status":"ok","providers":["lmstudio"]}`. `POST /v1/chat/completions` (non-stream only for this step) returns a hardcoded valid OpenAI response. Print startup banner. Add request ID middleware or header. (CI from step 1 will run ruff + the trivial health test against this.)  
   Dependencies: Step 1.  
   Mergeable: Yes — demonstrates the server runs and clients can point at it.

**Phase 1: Configuration & Routing**
3. **Config loader + provider model + env secret resolution**  
   Affected: `src/tiny_llm_proxy/config.py` (new), update example config + README, add unit tests in `tests/test_config.py` (using the test harness + ruff/CI scaffolding from step 1).  
   Description: Load YAML (with `${VAR}` expansion for keys), validate minimal schema (providers must have `base_url`), resolve `api_key_env`, produce a clean runtime `Config` dataclass or Pydantic model. Never store literal keys after resolution for logging paths. Support `--config` CLI arg and `TINYLLM_CONFIG`. Startup must fail fast on bad config.  
   Dependencies: Step 1-2 (to exercise at startup).  
   Mergeable: Yes (can be behind a feature flag or just used by later steps).

4. **Routing logic (prefix map + headers)**  
   Affected: `src/tiny_llm_proxy/routing.py` (new), `tests/test_routing.py` (using harness from step 1), integrate into server.  
   Description: Given request `model` + headers, return `(provider_name, rewritten_model_or_original)`. Implement prefix stripping using the map from config. Header names from config take precedence. Fall back to `default_provider`. Add logging of routing decision (without keys).  
   Dependencies: Step 3.  
   Mergeable: Yes.

**Phase 2: Core Proxying (Non-Streaming First)**
5. **Provider-aware request forwarding (non-streaming)**  
   Affected: `src/tiny_llm_proxy/forward.py` (new), `server.py` updates, `utils.py` (header sanitization).  
   Description: For a selected provider, build `httpx` client (reuse one global async client), inject `Authorization` if key present + any `extra_headers`, rewrite `model` in body if prefix was used, POST to `{base_url}/v1/chat/completions`, return the response (status + json). Handle basic errors by returning backend error body. Add duration timing.  
   Dependencies: Steps 3-4.  
   Mergeable: Yes — non-stream path can be complete and useful.

6. **Integrate non-stream path end-to-end + basic observability**  
   Affected: `server.py`, `main.py`, console logging improvements.  
   Description: Wire routing → forward → return. Add struct-ish INFO logs on request start/complete (req_id, provider, model, duration, tokens if present). Update health to reflect configured providers. Test manually with `curl` and Python `openai` SDK against LM Studio (or a mock).  
   Dependencies: Step 5.  
   Mergeable: Yes.

**Phase 3: Streaming + Logging (The Core Value)**
7. **Streaming forward + delta reconstruction**  
   Affected: `src/tiny_llm_proxy/streaming.py` (new, with pure reconstruct function + examples from design), `forward.py` updates, `server.py` (StreamingResponse). (Tests for the pure helper go in `tests/test_streaming.py` using step-1 harness.)  
   Description: Implement async generator that forwards SSE lines live while parsing `data:` JSON for deltas. Accumulate content and tool_calls (handle index-based partials). Support `include_usage`. On completion produce the canonical `assistant_message` dict + usage. Expose a sync test helper: `reconstruct_assistant_from_chunks(list[dict]) -> dict`. Handle client disconnect gracefully.  
   Dependencies: Step 5-6 (reuse forward patterns).  
   Mergeable: Yes (can land streaming even before persistent logging).

8. **Message logging module + JSONL writer**  
   Affected: `src/tiny_llm_proxy/logging.py` (new), `tests/test_logging.py` (using step-1 harness + request_id), integration in server/forward after reconstruction.  
   Description: `log_interaction(record: dict)` that:
   - Takes the normalized interaction (id, timestamp, provider, messages, assistant_message, usage, ...).
   - Redacts any accidental sensitive fields.
   - Computes/ensures date partition.
   - Appends one JSON line (with `ensure_ascii=False` for Chinese) to the daily file, creating dirs as needed.
   - Optional: if `log_raw`, also write redacted raw req/resp under `raw/`.
   Add a small CLI helper or just document `jq` usage. Make the writer safe for concurrent requests (simple file append is usually ok under low load; use locking if needed later).  
   Dependencies: Step 7 (needs the reconstructed message).  
   Mergeable: Yes — can be added and tested independently then wired.

9. **Wire streaming + logging into the full chat endpoint**  
   Affected: `server.py` (both branches), end-to-end tests or manual scripts.  
   Description: Non-stream path also calls the logger (after response). Streaming path calls logger after reconstruction (post-stream to client). Ensure request ID is threaded through. Add "streamed" flag to records. Verify with real LM Studio + OpenRouter (small prompts).  
   Dependencies: Steps 7-8.  
   Mergeable: This is the big integration step; aim for a working MVP here.

**Phase 4: Polish, Models Endpoint, Documentation, Release Prep**
10. **`/v1/models` support + remaining endpoints + error polish**  
    Affected: `server.py`, forward (reuse for models), README.  
    Description: `GET /v1/models` proxies to the default provider's equivalent (or a designated "models_provider"). Return the backend's JSON. Add `/` info page. Improve error responses to be valid OpenAI error objects. Add more header redaction and edge-case handling (empty messages, huge payloads).  
    Dependencies: Step 6+ (forwarding exists).  
    Mergeable: Yes.

11. **Full documentation, examples, and usability**  
    Affected: `README.md` (major update), `config.example.yaml` (complete), perhaps a `docs/` or just inline.  
    Description: 
    - Installation (`uv tool install` or `pipx` or `uv run`).
    - Full config explanation + copy-paste `config.yaml`.
    - Client configuration snippets: raw `openai` SDK (Python/TS), Continue.dev `config.json` (baseUrl + model prefixes or extra headers), Cursor, Open WebUI.
    - LM Studio quickstart and OpenRouter (including required referer headers).
    - How to inspect logs: `tail`, `jq` examples (filter by provider, extract messages for training, count tokens).
    - Future: how to add a new provider (llamacpp example).
    - Security/privacy warning section.
    - Development: how to run tests, format, contribute.
    - Traditional Chinese note or section for user-facing strings if we i18n later (for now, keep English + example prompts in Chinese).  
    Dependencies: Most previous (needs working system).  
    Mergeable: Yes — docs can be reviewed separately.

12. **Expand tests + integration smoke + CI polish, version bump, release**  
    Affected: `tests/`, `.github/workflows/ci.yml` (expand the skeleton from step 1), `pyproject.toml` version, CHANGELOG or release notes in README.  
    Description: Expand unit tests (config, routing, streaming reconstruction pure helper with the exact chunk vectors from the design doc, logging with request_id). Add integration smoke test that starts the server in-process and hits endpoints with mocked httpx (or real LM Studio if available). Ruff + basic type check already enforced by early CI. Enhance GitHub Actions (matrix, coverage if desired). Tag v0.1.0. Add the footprint check (see Issue 2 resolution below) as a manual or CI step note.  
    Dependencies: Step 11.  
    Mergeable: Can be a final PR or combined.

**Estimated order & parallelism notes**:
- Steps 1-2 can be done first and merged quickly to have a living repo (with CI + tests/ harness active immediately for all follow-on work).
- Config + routing (3-4) are independent of the HTTP bits and can be developed/tested in parallel with early server work (CI will enforce from day 1).
- Non-stream forward (5-6) gives immediate value.
- Streaming reconstruction (7) + logging (8) are the technically interesting pieces and have good test surfaces (pure helper + request_id threading).
- The final wiring + docs (9-11) turn it into a shippable personal tool.
- Total core Python LOC target for MVP after all steps: ~800-1200 lines (see Tiny Scope Trade-offs).

**Post-MVP (not in this plan)**: Add llamacpp as first-class in example config, simple proxy bearer auth, raw logging by default off with docs, better tool_calls streaming edge cases, vision log size warnings, a small `tiny-llm-proxy logs` subcommand for querying, Prometheus metrics, etc. Only after the owner has used the v1 for a while.

---

## Appendix: Example Log Line (Chinese prompt, full record)

```json
{"request_id":"req_01hxyz123abc","id":"chatcmpl-abc","timestamp":"2026-06-07T14:22:33.456789+08:00","duration_ms":1247,"provider":"openrouter","client_model":"openrouter/openai/gpt-4o-mini","backend_model":"openai/gpt-4o-mini","streamed":true,"messages":[{"role":"system","content":"你是一個有幫助的助手。"},{"role":"user","content":"請用繁體中文解釋代理伺服器的好處。"}],"assistant_message":{"role":"assistant","content":"代理伺服器可以讓你統一管理多個 LLM 後端，並且完整記錄每一次對話內容，方便之後檢視、除錯或做成訓練資料集。","tool_calls":null},"finish_reason":"stop","usage":{"prompt_tokens":28,"completion_tokens":67,"total_tokens":95},"extra":{"headers_snapshot":{"user-agent":"Continue.dev"}}}
```

This is directly usable:
```bash
jq '.messages + [.assistant_message]' logs/2026-06-07/interactions-2026-06-07.jsonl
```

---

*End of Design Document.*

This is the authoritative, consolidated design specification and implementation planning document for tiny-llm-proxy v0.1. It incorporates the original design plus all review feedback and clarifications (early CI scaffolding, Tiny Scope Trade-offs with footprint gate, consistent config schema, `request_id` in logs, concrete streaming reconstruction examples + pure helper, explicit header/auth rules, generic paths, etc.).

Implementation **must** follow the PR Plan strictly (12 steps in 4 phases, starting from the bottom/setup and working upward). Each step produces a mergeable increment. All data models, routing rules, streaming logic, log shapes, and key decisions are documented above for reference during development, testing, and code review.

The original temporary planning files (grok-design-*.md) are superseded and removed after consolidation.

