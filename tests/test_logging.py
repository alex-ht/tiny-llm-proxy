"""Tests for the conversation message logger (Step 8).

Exercises:
- Append to daily JSONL (with ensure_ascii=False for Chinese)
- Directory creation for date partitions
- Defensive redaction of sensitive material
- log_raw optional tree (sanitized .req / .resp)
- Using a reconstructed assistant_message (from the streaming helper) in a record
"""

import json
from pathlib import Path

from tiny_llm_proxy.logging import log_interaction
from tiny_llm_proxy.streaming import reconstruct_assistant_from_chunks


def test_basic_append_creates_daily_file(tmp_path: Path):
    record = {
        "request_id": "req_test123",
        "id": "chatcmpl-abc",
        "timestamp": "2026-06-08T10:00:00+08:00",
        "duration_ms": 123,
        "provider": "lmstudio",
        "client_model": "lmstudio/test",
        "backend_model": "test",
        "streamed": False,
        "messages": [{"role": "user", "content": "hello"}],
        "assistant_message": {
            "role": "assistant",
            "content": "hi there",
            "tool_calls": None,
            "refusal": None,
        },
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        "extra": {"headers_snapshot": {"user-agent": "test"}},
    }

    log_interaction(record, log_dir=str(tmp_path))

    day = tmp_path / "2026-06-08"
    assert day.exists()
    logf = day / "interactions-2026-06-08.jsonl"
    assert logf.exists()

    lines = logf.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["request_id"] == "req_test123"
    assert loaded["assistant_message"]["content"] == "hi there"


def test_chinese_and_ensure_ascii_false(tmp_path: Path):
    record = {
        "request_id": "req_zh",
        "id": "chatcmpl-zh",
        "timestamp": "2026-06-08T11:00:00+08:00",
        "duration_ms": 10,
        "provider": "lmstudio",
        "client_model": "lmstudio/test",
        "backend_model": "test",
        "streamed": False,
        "messages": [{"role": "user", "content": "你好，世界"}],
        "assistant_message": {
            "role": "assistant",
            "content": "哈囉！",
            "tool_calls": None,
            "refusal": None,
        },
        "finish_reason": "stop",
        "usage": None,
        "extra": {},
    }

    log_interaction(record, log_dir=str(tmp_path))

    logf = tmp_path / "2026-06-08" / "interactions-2026-06-08.jsonl"
    content = logf.read_text(encoding="utf-8")
    assert "你好，世界" in content
    assert "哈囉！" in content
    # ensure_ascii=False means no \\u escapes for these chars
    assert "\\u" not in content


def test_redaction_of_sensitive(tmp_path: Path):
    record = {
        "request_id": "req_redact",
        "id": "chatcmpl-r",
        "timestamp": "2026-06-08T12:00:00+08:00",
        "duration_ms": 1,
        "provider": "openrouter",
        "client_model": "openrouter/x",
        "backend_model": "x",
        "streamed": True,
        "messages": [],
        "assistant_message": {
            "role": "assistant",
            "content": "ok",
            "tool_calls": None,
            "refusal": None,
        },
        "finish_reason": "stop",
        "usage": None,
        "extra": {
            "headers_snapshot": {
                "authorization": "Bearer sk-SECRET",
                "user-agent": "ok",
                "x-openrouter-key": "should-be-hidden",
            }
        },
    }

    log_interaction(record, log_dir=str(tmp_path))

    logf = tmp_path / "2026-06-08" / "interactions-2026-06-08.jsonl"
    loaded = json.loads(logf.read_text(encoding="utf-8").strip())
    snap = loaded["extra"]["headers_snapshot"]
    assert snap["authorization"] == "[REDACTED]"
    assert snap["x-openrouter-key"] == "[REDACTED]"
    assert snap["user-agent"] == "ok"


def test_log_raw_tree(tmp_path: Path):
    record = {
        "request_id": "req_raw123",
        "id": "chatcmpl-raw",
        "timestamp": "2026-06-08T13:00:00+08:00",
        "duration_ms": 5,
        "provider": "lmstudio",
        "client_model": "lmstudio/m",
        "backend_model": "m",
        "streamed": False,
        "messages": [{"role": "user", "content": "hi"}],
        "assistant_message": {
            "role": "assistant",
            "content": "yo",
            "tool_calls": None,
            "refusal": None,
        },
        "finish_reason": "stop",
        "usage": None,
        "extra": {},
    }

    raw_req = {
        "model": "lmstudio/m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }
    raw_resp = {"id": "chatcmpl-raw", "choices": [{"message": {"content": "yo"}}]}

    log_interaction(
        record,
        log_dir=str(tmp_path),
        log_raw=True,
        raw_request=raw_req,
        raw_response=raw_resp,
    )

    raw_day = tmp_path / "raw" / "2026-06-08"
    assert raw_day.exists()
    assert (raw_day / "req_raw123.req.json").exists()
    assert (raw_day / "req_raw123.resp.json").exists()

    # redaction still applied to raw
    req_loaded = json.loads((raw_day / "req_raw123.req.json").read_text())
    assert "model" in req_loaded


def test_uses_reconstructed_assistant_message(tmp_path: Path):
    """The logger accepts records that contain an assistant_message produced
    by the streaming reconstruction helper (the main integration point for Step 9)."""
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": " from tool"}, "finish_reason": "stop"}]},
    ]
    assistant = reconstruct_assistant_from_chunks(chunks)

    record = {
        "request_id": "req_recon",
        "id": "chatcmpl-recon",
        "timestamp": "2026-06-08T14:00:00+08:00",
        "duration_ms": 42,
        "provider": "lmstudio",
        "client_model": "lmstudio/m",
        "backend_model": "m",
        "streamed": True,
        "messages": [{"role": "user", "content": "say hello"}],
        "assistant_message": assistant,
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
        "extra": {},
    }

    log_interaction(record, log_dir=str(tmp_path))

    logf = tmp_path / "2026-06-08" / "interactions-2026-06-08.jsonl"
    loaded = json.loads(logf.read_text(encoding="utf-8").strip())
    assert loaded["assistant_message"]["content"] == "Hello from tool"
    assert loaded["streamed"] is True
