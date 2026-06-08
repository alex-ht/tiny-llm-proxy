"""Entry point for the `tiny-llm-proxy` console script and `python -m tiny_llm_proxy`.

Step 3 (Phase 1): full config loading is wired.
- --config / TINYLLM_CONFIG respected
- Startup banner prints real provider names + base_urls (never keys)
- Server is created via the config-aware factory
- host/port and log level come from the loaded Config
"""

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from .config import load_config


def main(argv: list[str] | None = None) -> None:
    """Console script entrypoint.

    Loads configuration (respecting --config and TINYLLM_CONFIG), prints a
    safe startup banner, then launches uvicorn using the app factory.
    """
    parser = argparse.ArgumentParser(
        prog="tiny-llm-proxy",
        description="tiny-llm-proxy - minimal OpenAI-compatible proxy with local logging",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        metavar="PATH",
        help="Path to config file (overrides TINYLLM_CONFIG and search order)",
    )
    args = parser.parse_args(argv)

    # Make --config visible to load_config() inside the uvicorn worker
    # (including when --reload is used later).
    if args.config:
        os.environ["TINYLLM_CONFIG"] = str(Path(args.config).expanduser().resolve())

    cfg = load_config()

    # Startup banner - NEVER print secrets or resolved api keys
    print("tiny-llm-proxy v0.1.0")
    print(f"config: {cfg.config_path or 'built-in defaults'}")
    print("providers:")
    for name, p in cfg.providers.items():
        # Show only safe fields
        print(f"  - {name} ({p.get('base_url')})")
    print(f"log_dir: {cfg.log_dir}")
    print(f"default_provider: {cfg.default_provider}")
    print(f"log_level: {cfg.log_level}")
    print("OpenAPI docs: http://127.0.0.1:8000/docs")
    print("Press Ctrl+C to stop.\n")

    host = cfg.server.get("host", "127.0.0.1")
    port = int(cfg.server.get("port", 8000))

    # Use factory so create_app() inside the worker calls load_config()
    # again (picks up the env var we set above). This is reload-friendly.
    uvicorn.run(
        "tiny_llm_proxy.server:create_app",
        factory=True,
        host=host,
        port=port,
        log_level=cfg.log_level,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
