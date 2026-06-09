# tiny-llm-proxy

A **very small**, single-purpose OpenAI-compatible proxy server.

Its primary job is to sit between OpenAI-compatible clients (Continue.dev, Cursor, Open WebUI, custom `openai` SDK scripts, etc.) and one or more backend LLM servers (LM Studio, OpenRouter, and easily extensible), while providing **reliable local persistence** of every conversation turn.

**Key value**: the full `messages` array + the assistant's final response (reconstructed even from streaming deltas) + essential metadata are written to disk in a clean, queryable "message format" (OpenAI-style JSON objects, one per turn, daily-partitioned JSONL files). Perfect for later review, debugging, or turning into training datasets (ShareGPT, torchtune, etc.) with simple `jq`.

No heavy frameworks beyond the bounded FastAPI choice, no database, no UI, no cloud — just a tiny Python process you point your clients at via `base_url`.

## Installation

```bash
# Recommended for personal use
uv tool install git+https://github.com/alex-ht/tiny-llm-proxy.git

# Or with pipx
pipx install git+https://github.com/alex-ht/tiny-llm-proxy.git

# Development / from source
git clone https://github.com/alex-ht/tiny-llm-proxy.git
cd tiny-llm-proxy
uv sync --group dev
uv run tiny-llm-proxy --config config.example.yaml
```

You can also run directly without installing:
```bash
uv run --with git+https://github.com/alex-ht/tiny-llm-proxy.git tiny-llm-proxy --config config.yaml
```

## Quickstart (using the example remote llama.cpp + gemma-4-26b)

```bash
# 1. Copy the example config (never commit real keys)
cp config.example.yaml config.yaml

# 2. (Optional) If your remote service requires an API key
# export ALEXLLAMACPP_API_KEY=...

# 3. Install dependencies (this pulls in httpx etc.)
uv sync --group dev   # or without --group dev for runtime only

# 4. Run the proxy (ALWAYS use uv run so that httpx and other deps are available)
uv run tiny-llm-proxy --config config.yaml
# or with reload:
uv run uvicorn tiny_llm_proxy.server:create_app --factory --reload
```

**Important:** If you see "No module named 'httpx'" (or similar), it means you ran the proxy with a Python that doesn't have the project's dependencies. Always use `uv run ...` after `uv sync`. Do not use bare `python` or system uvicorn.

Point your clients at `http://127.0.0.1:8000/v1` (or `https://...` if you enabled SSL).

**Example model name** (this remote deployment):
- `llamacpp/gemma-4-26b`

Alternative header-based routing (takes precedence over prefix):
```
X-TinyLLM-Provider: alexllamacpp
```

Non-streaming requests are forwarded in real time and **automatically persisted** in the exact message format under `logs/`. 

This setup uses the **live remote llama.cpp service** at the exact URL you provided, serving the `gemma-4-26b` model as the primary concrete example throughout the docs and `config.example.yaml`.

**Verified usable**: A direct call to the backend using the exact model name the proxy forwards after stripping the prefix (`gemma-4-26b`) returns a valid OpenAI-compatible chat completion (200, usage stats, choices, etc.). The proxy will route `llamacpp/gemma-4-26b` → this backend correctly.

## HTTPS / SSL Support

If you need HTTPS (e.g. some clients or corporate policies require it):

1. Add under the `server:` section in your `config.yaml`:

```yaml
server:
  host: "127.0.0.1"
  port: 8443                 # common HTTPS port for local dev
  ssl_certfile: "cert.pem"
  ssl_keyfile: "key.pem"
```

2. Generate a self-signed certificate (quick & dirty for localhost):

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

3. Restart the proxy. The banner will show `https://127.0.0.1:8443/docs`.

**Notes / Warnings**:
- Self-signed certs will cause most clients (VS Code, browsers, some SDKs) to reject the connection by default. You will need to tell the client to accept insecure connections or import the cert into the system trust store.
- For a better experience on your machine, use [mkcert](https://github.com/FiloSottile/mkcert) — it generates locally-trusted certs.
- The `verify_ssl` option under a provider (default: true) controls whether the *proxy* verifies the backend's certificate when connecting to it (for both chat and /v1/models). For the remote gov.tw llama.cpp service (or any internal/self-signed HTTPS backend), you **must** set `verify_ssl: false`, otherwise you will get exactly:

  `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Missing Subject Key Identifier`

  (This was previously ignored for the models endpoint; now fixed to respect the setting.)
- **Recommended for most people**: Put a reverse proxy in front (Caddy is the easiest):

  Simple `Caddyfile`:
  ```
  :8443 {
      reverse_proxy localhost:8000
  }
  ```
  Caddy will automatically provide HTTPS (even with a real certificate if you use a public domain).

  Then point clients at `https://127.0.0.1:8443/v1` and keep the proxy itself on plain HTTP on 8000.

Direct SSL in uvicorn is supported for convenience, but a reverse proxy is more flexible and the usual way to do HTTPS in production setups.

## Configuration

Copy `config.example.yaml` to `config.yaml` (or any path via `--config` / `TINYLLM_CONFIG`).

Full current example (using the live remote llama.cpp service + gemma-4-26b as the concrete example):

```yaml
# tiny-llm-proxy configuration
server:
  host: "127.0.0.1"
  port: 8000

logging:
  level: "info"

log_dir: "./logs"
log_raw: false
log_streams_only: true     # default: 只記錄串流互動（同步訊息通常較不重要）

default_provider: "alexllamacpp"   # 這個遠端 llama.cpp 服務（gemma-4-26b）

providers:
  alexllamacpp:
    base_url: "https://afspod-services.dginfra.gov.tw/edb9267c-46f9-42f3-bb9a-dd0f1b5ebce6/alexllamacpp"
    # api_key_env: "ALEXLLAMACPP_API_KEY"   # 若服務需要金鑰
    # verify_ssl: false                     # 只有自簽憑證時才加

  # 其他併存後端範例（可選）
  lmstudio:
    base_url: "http://localhost:1234/v1"
    api_key: null

routing:
  prefix_map:
    "llamacpp/": "alexllamacpp"
    "remote/": "alexllamacpp"
    "lmstudio/": "lmstudio"
    "openrouter/": "openrouter"

  header_names: ["X-TinyLLM-Provider", "X-Provider", "X-LLM-Provider"]
```

Key points:
- `api_key` in YAML is only for local testing. Prefer `api_key_env`.
- For local providers (lmstudio, llama.cpp) `api_key: null` is correct — no Authorization header will be sent.
- OpenRouter requires the `extra_headers` (Referer + Title) for attribution.
- `log_raw: true` writes full (redacted) request/response JSONs under `logs/raw/`.

## Client Configuration

### Raw openai SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="dummy-or-anything",
)

resp = client.chat.completions.create(
    model="llamacpp/gemma-4-26b",   # ← 使用這個遠端範例模型
    messages=[{"role": "user", "content": "你好，請用一句話介紹自己。"}],
    max_tokens=50
)
print(resp.choices[0].message.content)
```

TypeScript / other languages work the same (just change `baseURL`). The model name `llamacpp/gemma-4-26b` will be routed to the remote alexllamacpp backend (prefix stripped).

### Continue.dev

In `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "GPT-4o (via tiny-llm-proxy)",
      "provider": "openai",
      "model": "openrouter/openai/gpt-4o",
      "apiBase": "http://127.0.0.1:8000/v1",
      "apiKey": "dummy"
    }
  ],
  "tabAutocompleteModel": { ... same pattern ... }
}
```

You can also put routing info in `extraHeaders` instead of the model name.

### Cursor

Settings → Models → Add OpenAI-compatible provider:

- Base URL: `http://127.0.0.1:8000/v1`
- API Key: `dummy`
- Model: `openrouter/openai/gpt-4o-mini` (or use header override in advanced settings)

### Open WebUI

Add an OpenAI-compatible connection:

- Base URL: `http://127.0.0.1:8000/v1`
- API Key: (any value)
- Default model: use prefix or select after it loads via `/v1/models`

## LM Studio Quickstart

1. Start LM Studio and load a model (server on `http://localhost:1234`).
2. In `config.yaml` set `default_provider: "lmstudio"`.
3. Run the proxy.
4. In any client use model names like `llama-3.2-3b` (no prefix needed if lmstudio is default) or `lmstudio/llama-3.2-3b`.

No API key is required on the client side for pure LM Studio usage.

## OpenRouter Quickstart

1. Get an API key from openrouter.ai.
2. `export OPENROUTER_API_KEY=sk-or-...`
3. In `config.yaml` the `openrouter` provider already has the required `extra_headers`.
4. Use models like `openrouter/openai/gpt-4o-mini` or `or/anthropic/claude-3.5-sonnet`.

The proxy automatically adds the `HTTP-Referer` and `X-OpenRouter-Title` headers required by OpenRouter.

## Inspecting Logs

Logs are written to `logs/<YYYY-MM-DD>/interactions-<YYYY-MM-DD>.jsonl`.

Basic inspection:
```bash
tail -f logs/$(date +%Y-%m-%d)/interactions-*.jsonl
```

Extract full conversation for training / review:
```bash
jq '.messages + [.assistant_message]' logs/*/*.jsonl > training.jsonl
```

Filter by provider:
```bash
jq 'select(.provider == "openrouter")' logs/*/*.jsonl
```

Count tokens across sessions:
```bash
jq -s 'map(.usage.total_tokens // 0) | add' logs/*/*.jsonl
```

The format is directly usable by many tools (ShareGPT converters, torchtune, Axolotl, etc.).

## Adding a New Provider (example: llama.cpp, including remote)

1. For a local llama.cpp server, start it with OpenAI-compatible endpoint (usually `http://localhost:8080/v1`).

   For remote (like your afspod-services deployment), just use the full HTTPS URL as base_url.

2. Add (or uncomment) the provider in your `config.yaml`:

```yaml
providers:
  # Local example
  # llamacpp:
  #   base_url: "http://localhost:8080/v1"
  #   api_key: "sk-no-key-required"

  # Remote llama.cpp (HTTPS example)
  alexllamacpp:
    base_url: "https://afspod-services.dginfra.gov.tw/edb9267c-46f9-42f3-bb9a-dd0f1b5ebce6/alexllamacpp"
    # api_key_env: "ALEXLLAMACPP_API_KEY"   # if the service requires auth
    # verify_ssl: false                     # only needed for self-signed / internal certs
```

3. Add to routing:

```yaml
routing:
  prefix_map:
    "llamacpp/": "alexllamacpp"
    # or "remote/": "alexllamacpp"
```

4. Use `llamacpp/your-model-name` (or `remote/...`) in clients. The prefix is stripped before forwarding to the backend.

If you get certificate errors when connecting to the remote backend, add `verify_ssl: false` under that provider (we added this option for exactly such cases).

## Security & Privacy

**Important warnings** (also in DESIGN.md):

- Every full conversation (system prompts, user messages, tool results, vision images/base64, assistant replies) is written to disk.
- This can contain private code, personal data, or secrets you accidentally pasted.
- **You are responsible** for protecting the `log_dir`:
  - Use `chmod 700 logs` (or stronger).
  - Consider encryption at rest on shared machines.
  - Exclude the logs directory from cloud backups/sync.
- The proxy performs **no automatic PII scrubbing**.
- Never commit real API keys to `config.yaml`. Use environment variables (`*_API_KEY`).
- The proxy never forwards your client `Authorization` header to backends.
- Default bind is `127.0.0.1` only. Do not expose publicly without adding your own auth layer.

Vision payloads (base64 images) can make log files large — monitor disk usage.

## Development

```bash
# Install everything (including httpx for the proxy itself)
uv sync --group dev

uv run ruff check .
uv run ruff format --check .
uv run pytest

# Run the proxy (this ensures httpx is in the environment)
uv run tiny-llm-proxy --config config.example.yaml
# or
uv run uvicorn tiny_llm_proxy.server:create_app --factory --reload
```

**Never run with bare `python` or `uvicorn` from outside the uv environment**, or you will get "No module named 'httpx'" etc.

The project aims to stay tiny and understandable in < 30 minutes for a new reader.

## Notes on Traditional Chinese

User-facing examples and sample prompts in this project (especially in log samples and this README) use Traditional Chinese (繁體中文) to match the original author's preference. The CLI, code, and configuration remain in English.

## License

MIT (see LICENSE).

---

See [DESIGN.md](DESIGN.md) for the complete architecture, exact JSON record shape, streaming reconstruction algorithm + test vectors, Header & Auth Construction Rules, and the original 12-step implementation plan.