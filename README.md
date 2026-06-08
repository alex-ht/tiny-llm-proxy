# tiny-llm-proxy

A **very small**, single-purpose OpenAI-compatible proxy server.

Its primary job is to sit between OpenAI-compatible clients (Continue.dev, Cursor, Open WebUI, custom `openai` SDK scripts, etc.) and one or more backend LLM servers (LM Studio, OpenRouter, and easily extensible), while providing **reliable local persistence** of every conversation turn.

**Key value**: the full `messages` array + the assistant's final response (reconstructed even from streaming deltas) + essential metadata are written to disk in a clean, queryable "message format" (OpenAI-style JSON objects, one per turn, daily-partitioned JSONL files). Perfect for later review, debugging, or turning into training datasets (ShareGPT, torchtune, etc.) with simple `jq`.

No heavy frameworks beyond the bounded FastAPI choice, no database, no UI, no cloud — just a tiny Python process you point your clients at via `base_url`.

## Status

Core implementation complete per the DESIGN.md plan (up through Step 10 + main wiring of Steps 8/9):

- Real non-stream forwarding to LM Studio / OpenRouter (exact auth + header rules).
- Prefix or `X-Provider` header routing.
- **Core value delivered**: non-stream conversations are persisted in the exact "message format" (daily JSONL, `messages` + reconstructed `assistant_message`, metadata). Usable with `jq` / ShareGPT / training tools.
- Streaming: live passthrough + accumulation + pure `reconstruct_assistant_from_chunks` (exact examples from the design are tested).
- Observability logs + `/v1/models` + root info.

See [DESIGN.md](DESIGN.md) for architecture, data model, the full 12-step plan, and remaining items (more client examples in README, expanded tests, footprint gate in CI, v0.1.0 release).

(As of the last implementation pass the src core is ~1180 lines including comments/docstrings — well within the spirit of the "tiny" targets after accounting for the implemented feature surface.)

## Quickstart

```bash
# 1. Config (never commit real keys)
cp config.example.yaml config.yaml
# export OPENROUTER_API_KEY=sk-or-...   # if using OpenRouter

# 2. Run
uv run tiny-llm-proxy --config config.yaml
```

Point clients at `http://127.0.0.1:8000/v1`.

Non-stream calls are forwarded for real and automatically logged in the exact "message format" (see DESIGN.md for the JSON shape and jq examples).

Use prefixes or the header for routing (see DESIGN.md for current details and client snippets for Continue.dev / Cursor / raw SDK).
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
