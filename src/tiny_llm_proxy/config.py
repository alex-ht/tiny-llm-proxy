"""Configuration loader for tiny-llm-proxy.

Implements the schema and loading rules from DESIGN.md Step 3:
- YAML (config.yaml / config.example.yaml / TINYLLM_CONFIG / --config)
- Recursive ${VAR} / $VAR expansion (small pure helper)
- api_key_env resolution (env wins over literal api_key in YAML)
- Minimal validation (every provider requires base_url)
- Runtime Config dataclass (exposes providers with *resolved* api_key only for
  injection use; never intended to be logged as-is)
- Fail fast on bad/missing config when explicitly provided
- Defaults allow the dummy server + tests to work out-of-the-box using
  the shipped config.example.yaml

No pydantic-settings; only stdlib + pyyaml (already a dep).
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Built-in defaults matching config.example.yaml so that a fresh clone
# + `uv run tiny-llm-proxy` works without the user copying files first.
# User config (config.yaml) takes precedence when present.
DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8000},
    "logging": {"level": "info"},
    "log_dir": "./logs",
    "log_raw": False,
    "log_streams_only": True,  # default: only persist streaming interactions to the main JSONL (sync messages are usually less important)
    "default_provider": "lmstudio",
    "providers": {
        "lmstudio": {
            "base_url": "http://localhost:1234/v1",
            "api_key": None,
        },
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            # extra_headers added at load time from example, but we keep
            # whatever the yaml supplies under extra_headers.
        },
    },
    "routing": {
        "prefix_map": {
            "lmstudio/": "lmstudio",
            "openrouter/": "openrouter",
            "or/": "openrouter",
            "llamacpp/": "llamacpp",
            "local/": "lmstudio",
        },
        "header_names": ["X-TinyLLM-Provider", "X-Provider", "X-LLM-Provider"],
    },
}


def _expand_vars(value: Any, environ: dict[str, str] | None = None) -> Any:
    """Recursively expand ${VAR} and $VAR in strings (and nested structures).

    Missing variables are left unchanged (common safe behavior).
    This is the small expander described in DESIGN.md (~20 LOC).
    """
    if environ is None:
        environ = os.environ

    if isinstance(value, str):

        def _repl(m: re.Match[str]) -> str:
            var = m.group(1) or m.group(2)
            return environ.get(var, m.group(0))

        return re.sub(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)", _repl, value)

    if isinstance(value, dict):
        return {k: _expand_vars(v, environ) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_vars(v, environ) for v in value]
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge override into a copy of base (override wins for scalars)."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


@dataclass
class Config:
    """Runtime configuration object.

    providers[name]["api_key"] contains the *resolved* value (from env or yaml)
    and is only meant to be read by the forwarder for header injection.
    Logging / observability code must never emit these values.
    """

    server: dict[str, Any]
    logging: dict[str, Any]
    log_dir: str
    log_raw: bool
    log_streams_only: bool = True
    default_provider: str = "lmstudio"
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    _config_path: str | None = None

    @property
    def log_level(self) -> str:
        """Single source of verbosity (logging.level preferred; top-level log_level for compat)."""
        return str(self.logging.get("level") or "info").lower()

    def get_provider(self, name: str) -> dict[str, Any]:
        if name not in self.providers:
            raise KeyError(f"Unknown provider '{name}'. Known: {list(self.providers)}")
        return self.providers[name]

    @property
    def config_path(self) -> str | None:
        return self._config_path


def load_config(config_path: str | None = None) -> Config:
    """Load, expand, resolve secrets, validate and return a Config.

    Resolution order for the file:
      1. Explicit config_path arg
      2. TINYLLM_CONFIG env var
      3. config.yaml / config.yml in CWD
      4. config.example.yaml (shipped default - allows immediate `uv run`)

    If an explicit path is given and does not exist -> FileNotFoundError (fail fast).
    """
    environ = os.environ
    explicit = config_path or environ.get("TINYLLM_CONFIG")
    raw: dict[str, Any] = {}
    used_path: Path | None = None

    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        used_path = p
        with open(p, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    else:
        for candidate in ("config.yaml", "config.yml", "config.example.yaml"):
            p = Path(candidate)
            if p.exists():
                used_path = p.resolve()
                with open(p, encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                break

    # Merge user/raw over defaults, then expand env vars
    merged = _deep_merge(DEFAULT_CONFIG, raw)
    expanded = _expand_vars(merged, environ)

    # Resolve api_key / api_key_env per provider (env wins)
    resolved_providers: dict[str, dict[str, Any]] = {}
    for name, p in expanded.get("providers", {}).items():
        p = dict(p)  # shallow copy
        api_key = p.get("api_key")
        api_key_env = p.pop("api_key_env", None)

        if api_key_env:
            env_val = environ.get(api_key_env)
            if env_val is not None:
                api_key = env_val

        # Store only the final resolved value (or None). Strip empty strings.
        if api_key and str(api_key).strip():
            p["api_key"] = str(api_key)
        else:
            p["api_key"] = None

        # Remove the _env key from the final provider dict
        p.pop("api_key_env", None)

        base_url = p.get("base_url")
        if not base_url or not str(base_url).strip():
            raise ValueError(
                f"Provider '{name}' is missing a required 'base_url' "
                "(see config schema in DESIGN.md)"
            )

        resolved_providers[name] = p

    # logging section + top-level log_level compat (as documented in DESIGN.md)
    # Top-level "log_level" wins if present (for backward compat in the loader).
    log_level = expanded.get("log_level")
    if log_level is None:
        log_level = expanded.get("logging", {}).get("level")
    logging_section = {"level": str(log_level or "info").lower()}

    cfg = Config(
        server=dict(expanded.get("server", DEFAULT_CONFIG["server"])),
        logging=logging_section,
        log_dir=str(expanded.get("log_dir", "./logs")),
        log_raw=bool(expanded.get("log_raw", False)),
        log_streams_only=bool(expanded.get("log_streams_only", True)),
        default_provider=str(expanded.get("default_provider", "lmstudio")),
        providers=resolved_providers,
        routing=dict(expanded.get("routing", DEFAULT_CONFIG["routing"])),
        _config_path=str(used_path) if used_path else None,
    )
    return cfg
