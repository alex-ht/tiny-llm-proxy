"""tiny-llm-proxy

A very small, single-purpose OpenAI-compatible proxy server.

Primary value: reliable local persistence of every conversation turn
in clean "message format" (daily JSONL, directly usable for jq/ShareGPT/torchtune/etc).

See DESIGN.md for the full specification, data models, architecture,
streaming reconstruction rules, config schema, and the 12-step PR plan.
"""

__version__ = "0.1.0"
