"""Small shared utilities (request ids, timing, header redaction, etc.).

Kept tiny; will grow only as needed in later steps.
"""

import uuid


def generate_request_id() -> str:
    """Return a short, URL-safe unique request identifier.

    Used for:
    - X-Request-ID response header
    - correlation in console logs and (later) conversation logs
    - error traces
    """
    # Short enough to be readable in logs/headers, unique enough for personal use.
    return "req_" + uuid.uuid4().hex[:12]
