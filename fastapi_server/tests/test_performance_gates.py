from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import select

from fastapi_server.auth import User
from fastapi_server.db import init_db, item, project, session_scope
from fastapi_server.main import ingest_events
from fastapi_server.schemas import EventsIngestRequest
from scripts.seed import main as seed_main

LOCAL_SYNC_ACK_P95_MS_GATE = 2000


@pytest.fixture(autouse=True)
def _seed_db() -> None:
    init_db()
    seed_main()


def _project_id() -> str:
    with session_scope() as session:
        return session.execute(select(project.c.id)).scalar_one()


def _first_item_id() -> str:
    with session_scope() as session:
        stmt = select(item.c.id).order_by(item.c.sort_key.asc()).limit(1)
        return session.execute(stmt).scalar_one()


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, int(0.95 * len(ordered)) - 1)
    return ordered[idx]


def test_sync_ack_latency_p95_gate_local():
    pid = _project_id()
    iid = _first_item_id()
    user = User(user_id="reviewer@example.com", email="reviewer@example.com")

    latencies_ms: list[float] = []
    for _ in range(120):
        payload = EventsIngestRequest(
            client_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            events=[
                {
                    "event_id": str(uuid.uuid4()),
                    "item_id": iid,
                    "decision_id": "pass",
                    "note": "",
                    "ts_client": int(time.time() * 1000),
                }
            ],
        )
        t0 = time.perf_counter()
        out = ingest_events(project_id=pid, payload=payload, user=user)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert out["accepted"] == 1
        latencies_ms.append(elapsed_ms)

    p95_ms = _p95(latencies_ms)
    assert p95_ms < LOCAL_SYNC_ACK_P95_MS_GATE, (
        f"p95 sync ack latency {p95_ms:.2f}ms exceeds "
        f"{LOCAL_SYNC_ACK_P95_MS_GATE}ms gate"
    )
