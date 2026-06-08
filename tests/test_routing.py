"""Unit tests for routing (prefix map + header override).

Covers the hybrid strategy documented in DESIGN.md and the PR Plan Step 4.
"""

from tiny_llm_proxy.config import load_config
from tiny_llm_proxy.routing import route_request


def _cfg():
    # Use the real shipped example so we test against the documented prefix_map
    # and header_names without duplicating them here.
    return load_config()


def test_prefix_lmstudio():
    cfg = _cfg()
    provider, model = route_request("lmstudio/llama-3.2-3b", {}, cfg)
    assert provider == "lmstudio"
    assert model == "llama-3.2-3b"


def test_prefix_openrouter():
    cfg = _cfg()
    provider, model = route_request("openrouter/openai/gpt-4o-mini", {}, cfg)
    assert provider == "openrouter"
    assert model == "openai/gpt-4o-mini"


def test_prefix_or_alias():
    cfg = _cfg()
    provider, model = route_request("or/anthropic/claude-3-5-sonnet", {}, cfg)
    assert provider == "openrouter"
    assert model == "anthropic/claude-3-5-sonnet"


def test_header_wins_over_prefix():
    cfg = _cfg()
    headers = {"X-TinyLLM-Provider": "openrouter"}
    provider, model = route_request("lmstudio/some-local-model", headers, cfg)
    assert provider == "openrouter"
    # model is passed through unchanged when header routing is used
    assert model == "lmstudio/some-local-model"


def test_header_case_insensitive():
    cfg = _cfg()
    headers = {"x-provider": "openrouter"}  # lower case
    provider, model = route_request("foo", headers, cfg)
    assert provider == "openrouter"
    assert model == "foo"


def test_custom_header_name():
    cfg = _cfg()
    headers = {"X-LLM-Provider": "lmstudio"}
    provider, model = route_request("anything", headers, cfg)
    assert provider == "lmstudio"


def test_falls_back_to_default():
    cfg = _cfg()
    provider, model = route_request("just-a-model-name-without-prefix", {}, cfg)
    assert provider == cfg.default_provider
    assert model == "just-a-model-name-without-prefix"


def test_unknown_prefix_falls_to_default():
    cfg = _cfg()
    provider, model = route_request("weirdprefix/some-model", {}, cfg)
    assert provider == cfg.default_provider
    assert model == "weirdprefix/some-model"


def test_header_with_no_prefix_still_works():
    cfg = _cfg()
    headers = {"X-Provider": "openrouter"}
    provider, model = route_request("gpt-4o", headers, cfg)
    assert provider == "openrouter"
    assert model == "gpt-4o"


def test_empty_after_strip_keeps_original():
    """If someone sends exactly the prefix, we keep the original model so the
    backend gets a chance to error in a visible way."""
    cfg = _cfg()
    provider, model = route_request("openrouter/", {}, cfg)
    assert provider == "openrouter"
    assert model == "openrouter/"  # or the original; either is acceptable


def test_routing_with_minimal_config():
    """Routing works even with a hand-crafted tiny Config (important for unit tests)."""
    from tiny_llm_proxy.config import Config

    tiny_cfg = Config(
        server={},
        logging={},
        log_dir="./logs",
        log_raw=False,
        default_provider="lmstudio",
        providers={"lmstudio": {"base_url": "http://x"}, "openrouter": {"base_url": "http://y"}},
        routing={
            "prefix_map": {"or/": "openrouter"},
            "header_names": ["X-Provider"],
        },
    )
    p, m = route_request("or/foo", {}, tiny_cfg)
    assert p == "openrouter"
    assert m == "foo"

    p2, m2 = route_request("bar", {"x-provider": "openrouter"}, tiny_cfg)
    assert p2 == "openrouter"
    assert m2 == "bar"
