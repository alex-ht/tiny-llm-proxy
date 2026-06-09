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

    server_cfg = cfg.server or {}
    host = server_cfg.get("host", "127.0.0.1")
    port = int(server_cfg.get("port", 8000))
    ssl_certfile = server_cfg.get("ssl_certfile")
    ssl_keyfile = server_cfg.get("ssl_keyfile")

    # Determine scheme for banner / docs link
    use_https = bool(ssl_certfile and ssl_keyfile)
    scheme = "https" if use_https else "http"
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host

    print(f"OpenAPI docs: {scheme}://{display_host}:{port}/docs")
    if use_https:
        print("HTTPS enabled (self-signed or custom cert). Clients may need to trust the certificate.")
    print("Press Ctrl+C to stop.\n")

    # Use factory so create_app() inside the worker calls load_config()
    # again (picks up the env var we set above). This is reload-friendly.
    uvicorn_kwargs = {
        "host": host,
        "port": port,
        "log_level": cfg.log_level,
    }
    if use_https:
        uvicorn_kwargs["ssl_certfile"] = ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile

    uvicorn.run(
        "tiny_llm_proxy.server:create_app",
        factory=True,
        **uvicorn_kwargs,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
