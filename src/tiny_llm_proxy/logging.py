"""Conversation message logging (the core value of the project).

Step 8: append-only daily JSONL writer in the exact "message format" shape
specified in DESIGN.md (Data Model section).

- One self-contained JSON object per /chat/completions turn.
- Daily partition under <log_dir>/<YYYY-MM-DD>/interactions-YYYY-MM-DD.jsonl
- ensure_ascii=False so Chinese (and other non-ASCII) text stays human readable.
- Defensive redaction of anything that looks like a secret before writing.
- Optional raw/ tree (sanitized full req + resp) when log_raw=True in config.
- Safe for low-concurrency personal use (plain append; POSIX small writes are
  atomic enough for this workload).

The actual building of the normalized record (messages + reconstructed
assistant_message + metadata) and the call to this module happen after
forwarding/reconstruction.

By default (log_streams_only: true in config), only streaming interactions
are persisted (sync ones are usually less valuable for review/training datasets).
Non-stream logging can be enabled by setting log_streams_only: false.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _redact_sensitive(obj: Any) -> Any:
    """Recursively redact obvious secrets in headers, extra, raw snapshots, etc.

    Used defensively by the logger (the real redaction for headers_snapshot
    should already have been done by the caller when building the record).
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            kl = k.lower()
            if any(
                x in kl
                for x in (
                    "auth",
                    "key",
                    "token",
                    "authorization",
                    "api_key",
                    "secret",
                    "bearer",
                )
            ):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact_sensitive(v)
        return out
    if isinstance(obj, list):
        return [_redact_sensitive(x) for x in obj]
    if isinstance(obj, str):
        if obj.startswith(("sk-", "Bearer ", "ghp_")):
            return "[REDACTED]"
        return obj
    return obj


def log_interaction(
    record: dict[str, Any],
    *,
    log_dir: str = "./logs",
    log_raw: bool = False,
    raw_request: dict[str, Any] | None = None,
    raw_response: dict[str, Any] | None = None,
) -> None:
    """Append a single normalized interaction record to the daily JSONL.

    The record must follow the shape documented in DESIGN.md (request_id,
    id, timestamp, duration_ms, provider, client_model, backend_model,
    streamed, messages, assistant_message, finish_reason, usage, extra).

    Creates the date directory if necessary.
    Always appends with a trailing newline.
    """
    # Derive the partition date from the record timestamp (fall back to now)
    ts = record.get("timestamp")
    try:
        if ts:
            # Accept ISO with or without Z / offset
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = datetime.now().astimezone()
    except Exception:
        dt = datetime.now().astimezone()

    date_str = dt.strftime("%Y-%m-%d")
    day_dir = Path(log_dir) / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    log_file = day_dir / f"interactions-{date_str}.jsonl"

    # Defensive redact before any write
    safe_record = _redact_sensitive(record)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(safe_record, ensure_ascii=False) + "\n")

    # Optional raw debug tree (redacted)
    if log_raw:
        raw_dir = Path(log_dir) / "raw" / date_str
        raw_dir.mkdir(parents=True, exist_ok=True)

        # Use request_id or backend id for the filename stem
        stem = (
            record.get("request_id")
            or record.get("id")
            or f"unknown-{datetime.now().timestamp():.0f}"
        )
        # Sanitize stem a bit for filesystem
        stem = "".join(c for c in str(stem) if c.isalnum() or c in "-_.")

        if raw_request is not None:
            req_path = raw_dir / f"{stem}.req.json"
            with open(req_path, "w", encoding="utf-8") as f:
                json.dump(_redact_sensitive(raw_request), f, ensure_ascii=False, indent=2)

        if raw_response is not None:
            resp_path = raw_dir / f"{stem}.resp.json"
            with open(resp_path, "w", encoding="utf-8") as f:
                json.dump(_redact_sensitive(raw_response), f, ensure_ascii=False, indent=2)
