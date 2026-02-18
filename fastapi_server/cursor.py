from __future__ import annotations

import base64
import json
from typing import Any

from fastapi_server.db import now_ms


def encode_cursor(payload: dict[str, Any], ttl_ms: int) -> str:
    data = {"payload": payload, "exp": now_ms() + ttl_ms}
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def decode_cursor(cursor: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(cursor.encode("utf-8"))
    data = json.loads(raw.decode("utf-8"))
    return data
