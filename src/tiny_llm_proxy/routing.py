"""Routing logic (model prefix + header override).

Implements the chosen hybrid strategy from DESIGN.md:
- Primary: model name prefix map (e.g. "openrouter/gpt-4o", "lmstudio/...", "or/...")
- Header override always wins if present (X-TinyLLM-Provider, X-Provider, X-LLM-Provider by default)
- Fall back to default_provider from config
- Returns (provider_name, rewritten_model) where rewritten_model has the prefix stripped
  when a prefix rule matched.

This module is pure (given model + headers dict + Config) so it is easy to unit test.
No secrets ever touch this code.
"""

from .config import Config


def _get_header(headers: dict[str, str], names: list[str]) -> str | None:
    """Case-insensitive lookup for one of the configured header names."""
    # Normalize incoming headers to lower for matching (common in HTTP libs too).
    lower_headers = {k.lower(): v for k, v in headers.items()}
    for name in names:
        val = lower_headers.get(name.lower())
        if val:
            return val.strip()
    return None


def route_request(
    model: str,
    headers: dict[str, str],
    config: Config,
) -> tuple[str, str]:
    """Decide which backend provider to use and what model name to send to it.

    Returns:
        (provider_name, backend_model)

    Rules (in order):
    1. If a configured routing.header_names value is present in the request headers,
       that provider is used and the original model is passed through (no prefix stripping).
    2. Otherwise, walk the config.routing.prefix_map (longest match first is nice but
       simple iteration is sufficient for the small maps we expect). Strip the prefix
       from the model if it matches.
    3. If nothing matched, use config.default_provider and the original model.
    """
    routing = config.routing or {}
    prefix_map: dict[str, str] = routing.get("prefix_map", {}) or {}
    header_names: list[str] = routing.get("header_names", []) or []

    # 1. Header override (highest priority)
    header_provider = _get_header(headers, header_names)
    if header_provider:
        # Header always wins; do not strip anything from the model.
        # The caller (forwarder) will still validate that the provider exists.
        return header_provider, model

    # 2. Prefix map (order in the dict is insertion order in Python 3.7+;
    #    for typical small maps this is fine. We can sort by prefix length desc
    #    for "most specific wins" if desired in the future.)
    model_lower = model.lower()  # prefixes are matched case-sensitively in examples,
    # but to be friendly we match on the original case
    # while the map keys are usually lowercase.
    for prefix, provider in prefix_map.items():
        if model.startswith(prefix) or model_lower.startswith(prefix.lower()):
            rewritten = model[len(prefix) :]
            # If after stripping we have an empty model, keep something sensible
            # (the backend will probably error, which is fine).
            if not rewritten:
                rewritten = model
            return provider, rewritten

    # 3. Default
    return config.default_provider, model


def get_provider_and_model(model: str, headers: dict[str, str], config: Config) -> tuple[str, str]:
    """Public alias used by the server/forwarder (same as route_request)."""
    return route_request(model, headers, config)
