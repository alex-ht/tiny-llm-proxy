"""Tests for streaming reconstruction (Step 7).

Focus on the pure `reconstruct_assistant_from_chunks` helper (no I/O, fully
unit-testable) using the exact input/output examples from DESIGN.md.

This makes the hard part of streaming (delta accumulation for content + tool_calls,
finish_reason, usage, edge cases) immediately verifiable and implementable.
"""

from tiny_llm_proxy.streaming import reconstruct_assistant_from_chunks


def test_reconstruct_content_only():
    """Content-only stream (typical case). Last chunk has finish_reason + usage."""
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}]},
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
    ]
    result = reconstruct_assistant_from_chunks(chunks)
    assert result == {
        "role": "assistant",
        "content": "Hello world",
        "tool_calls": None,
        "refusal": None,
    }


def test_reconstruct_parallel_tool_calls():
    """Parallel tool calls (name/id on first delta for index; arguments concatenated as strings)."""
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": ""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"city":'}}]},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]},
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    result = reconstruct_assistant_from_chunks(chunks)
    assert result == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
            }
        ],
        "refusal": None,
    }


def test_reconstruct_empty_content_pure_tool():
    """Empty content (pure tool call) should have content=None."""
    chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "do_something", "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    result = reconstruct_assistant_from_chunks(chunks)
    assert result["content"] is None
    assert result["tool_calls"] is not None
    assert result["tool_calls"][0]["function"]["name"] == "do_something"


def test_reconstruct_multiple_choices_takes_first():
    """Rare multiple choices: we take [0] per the spec."""
    chunks = [
        {
            "choices": [
                {"index": 0, "delta": {"content": "first"}, "finish_reason": "stop"},
                {"index": 1, "delta": {"content": "second"}, "finish_reason": "stop"},
            ]
        }
    ]
    result = reconstruct_assistant_from_chunks(chunks)
    assert result["content"] == "first"


def test_reconstruct_usage_on_final_chunk():
    """Usage may appear on the final chunk (include_usage)."""
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}]},
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        },
    ]
    result = reconstruct_assistant_from_chunks(chunks)
    # The helper itself only returns the assistant_message.
    # The caller (later) can also obtain usage/finish_reason if the signature evolves.
    assert result["content"] == "hi"
