"""Entry point for the `tiny-llm-proxy` console script and `python -m tiny_llm_proxy`.

Step 2 (Phase 0): provides a runnable uvicorn server with a startup banner.
Configuration loading, real provider list, and CLI flags beyond --config
are added in Step 3+.
"""

import argparse
import sys

import uvicorn


def main(argv: list[str] | None = None) -> None:
    """Console script entrypoint.

    Currently only supports a --config placeholder (ignored until the real
    config loader in Step 3). Prints a startup banner then launches uvicorn.
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
        help="Path to config.yaml (currently ignored - Step 2 dummy server)",
    )
    args = parser.parse_args(argv)

    # Startup banner (never log secrets / keys)
    print("tiny-llm-proxy v0.1.0 (Phase 0 Step 2 dummy)")
    print("providers:")
    print("  - lmstudio (http://localhost:1234/v1)   [stub; real config in Step 3]")
    print("log_dir: ./logs   (stub)")
    if args.config:
        print(f"(config file supplied: {args.config} — ignored in this step)")
    print("OpenAPI docs: http://127.0.0.1:8000/docs")
    print("Press Ctrl+C to stop.\n")

    # Use the string form so reload works nicely if someone adds --reload later.
    uvicorn.run(
        "tiny_llm_proxy.server:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        # reload=False for the dummy step (no source watching needed yet)
    )


if __name__ == "__main__":
    main(sys.argv[1:])
