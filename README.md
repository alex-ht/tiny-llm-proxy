# tiny-llm-proxy

A **very small**, single-purpose OpenAI-compatible proxy server.

Its primary job is to sit between OpenAI-compatible clients (Continue.dev, Cursor, Open WebUI, custom `openai` SDK scripts, etc.) and one or more backend LLM servers (LM Studio, OpenRouter, and easily extensible), while providing **reliable local persistence** of every conversation turn.

**Key value**: the full `messages` array + the assistant's final response (reconstructed even from streaming deltas) + essential metadata are written to disk in a clean, queryable "message format" (OpenAI-style JSON objects, one per turn, daily-partitioned JSONL files). Perfect for later review, debugging, or turning into training datasets (ShareGPT, torchtune, etc.) with simple `jq`.

No heavy frameworks beyond the bounded FastAPI choice, no database, no UI, no cloud — just a tiny Python process you point your clients at via `base_url`.

## Status

This is the initial scaffolding step (Phase 0 / Step 1 per DESIGN.md). The server is not yet runnable.

See [DESIGN.md](DESIGN.md) for:
- Complete architecture, sequence diagrams, and data model (exact log JSON shape)
- Configuration reference + `config.example.yaml`
- Streaming reconstruction logic and tool_calls handling
- Header/auth rules and security notes
- The full 12-step incremental PR plan (start from the bottom)

## Quickstart (after implementation)

```bash
# Copy and edit config (never commit real keys)
cp config.example.yaml config.yaml
# Set OPENROUTER_API_KEY=... in your env for OpenRouter

uv run tiny-llm-proxy --config config.yaml
# or: uv run uvicorn tiny_llm_proxy.server:app --reload
```

Point clients at `http://127.0.0.1:8000/v1`.

Use model prefixes for routing, e.g.:
- `lmstudio/llama-3.2-3b` (or just the model if lmstudio is default)
- `openrouter/openai/gpt-4o-mini`
- `or/anthropic/claude-3.5-sonnet`

Or send header `X-TinyLLM-Provider: openrouter` and use raw model names.

Inspect logs:
```bash
jq '.messages + [.assistant_message]' logs/2026-06-*/interactions-*.jsonl
```

## Development (current)

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`uv run tiny-llm-proxy` will become the entrypoint once the server (Step 2) is implemented.

## License

MIT (see LICENSE).
