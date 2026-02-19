from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger("triagedeck")

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_timings_ms: dict[str, list[float]] = defaultdict(list)


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str))


def increment(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] += value


def observe_ms(name: str, value: float) -> None:
    with _lock:
        _timings_ms[name].append(float(value))
        # Keep bounded in-memory history.
        if len(_timings_ms[name]) > 2000:
            _timings_ms[name] = _timings_ms[name][-2000:]


def snapshot() -> dict[str, Any]:
    with _lock:
        out = {"counters": dict(_counters), "timings_ms": {}}
        for name, values in _timings_ms.items():
            if not values:
                out["timings_ms"][name] = {"count": 0, "p95": 0.0}
                continue
            ordered = sorted(values)
            idx = max(0, int(0.95 * len(ordered)) - 1)
            out["timings_ms"][name] = {"count": len(values), "p95": ordered[idx]}
        return out
