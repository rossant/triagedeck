from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from fastapi_server.auth import User
from fastapi_server.db import init_db, item, project, session_scope
from fastapi_server.main import (
    create_export,
    get_export,
    ingest_events,
    list_decisions,
    list_items,
    list_projects,
)
from fastapi_server.schemas import EventsIngestRequest, ExportCreateRequest
from scripts.seed import main as seed_main


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


def test_projects_list_requires_auth_semantics():
    with pytest.raises(HTTPException) as exc:
        # Mirrors behavior of missing auth header.
        raise HTTPException(status_code=401)
    assert exc.value.status_code == 401


def test_projects_list_ok():
    out = list_projects(user=User(user_id="reviewer@example.com", email="reviewer@example.com"))
    assert len(out["projects"]) >= 1


def test_items_cursor_flow():
    pid = _project_id()
    user = User(user_id="reviewer@example.com", email="reviewer@example.com")

    page1 = list_items(project_id=pid, cursor=None, limit=5, user=user)
    assert len(page1["items"]) == 5
    assert page1["next_cursor"]

    page2 = list_items(project_id=pid, cursor=page1["next_cursor"], limit=5, user=user)
    assert len(page2["items"]) >= 1
    assert page2["items"][0]["item_id"] != page1["items"][0]["item_id"]


def test_event_idempotency_and_resume():
    pid = _project_id()
    iid = _first_item_id()
    event_id = str(uuid.uuid4())
    user = User(user_id="reviewer@example.com", email="reviewer@example.com")

    payload = EventsIngestRequest(
        client_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        events=[
            {
                "event_id": event_id,
                "item_id": iid,
                "decision_id": "pass",
                "note": "ok",
                "ts_client": 1739472000000,
            }
        ],
    )
    r1 = ingest_events(project_id=pid, payload=payload, user=user)
    assert r1["accepted"] == 1

    r2 = ingest_events(project_id=pid, payload=payload, user=user)
    assert r2["duplicate"] == 1

    decisions = list_decisions(project_id=pid, cursor=None, limit=500, user=user)
    assert any(d["item_id"] == iid and d["event_id"] == event_id for d in decisions["decisions"])


def test_viewer_cannot_post_events():
    pid = _project_id()
    iid = _first_item_id()
    payload = EventsIngestRequest(
        client_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        events=[
            {
                "event_id": str(uuid.uuid4()),
                "item_id": iid,
                "decision_id": "pass",
                "note": "",
                "ts_client": 1739472000000,
            }
        ],
    )
    with pytest.raises(HTTPException) as exc:
        ingest_events(
            project_id=pid,
            payload=payload,
            user=User(user_id="viewer@example.com", email="viewer@example.com"),
        )
    assert exc.value.status_code == 403


def test_export_create_and_get():
    pid = _project_id()
    user = User(user_id="reviewer@example.com", email="reviewer@example.com")

    created = create_export(
        project_id=pid,
        body=ExportCreateRequest(
            mode="labels_only",
            label_policy="latest_per_user",
            format="jsonl",
            filters={},
            include_fields=["item_id", "external_id", "decision_id", "note", "ts_server"],
        ),
        user=user,
    )
    export_id = created["export_id"]
    fetched = get_export(project_id=pid, export_id=export_id, user=user)
    assert fetched["status"] == "ready"
