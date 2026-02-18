from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from sqlalchemy import select

from fastapi_server.db import init_db, item, project, session_scope
from scripts.seed import main as seed_main

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])
    except PermissionError as exc:
        pytest.skip(f"Live HTTP tests skipped: socket operations are blocked ({exc})")


def _request(
    method: str, url: str, *, headers: dict[str, str] | None = None, body: dict | None = None
):
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = Request(url=url, method=method, headers=req_headers, data=data)
    with urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _wait_ready(base_url: str, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, _ = _request("GET", f"{base_url}/health")
            if status == 200:
                return
        except URLError:
            time.sleep(0.2)
    raise RuntimeError("Server did not become ready in time")


@pytest.fixture(scope="module")
def live_server() -> str:
    init_db()
    seed_main()

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "fastapi_server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_ready(base_url)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _project_id() -> str:
    with session_scope() as session:
        return session.execute(select(project.c.id)).scalar_one()


def _first_item_id() -> str:
    with session_scope() as session:
        stmt = select(item.c.id).order_by(item.c.sort_key.asc()).limit(1)
        return session.execute(stmt).scalar_one()


def test_http_projects_and_config(live_server: str):
    project_id = _project_id()
    headers = {"x-user-id": "reviewer@example.com"}

    status, body = _request("GET", f"{live_server}/api/v1/projects", headers=headers)
    assert status == 200
    assert len(body["projects"]) >= 1

    status, cfg = _request(
        "GET", f"{live_server}/api/v1/projects/{project_id}/config", headers=headers
    )
    assert status == 200
    assert cfg["max_compare_variants"] == 2


def test_http_items_cursor_and_single_item(live_server: str):
    project_id = _project_id()
    headers = {"x-user-id": "reviewer@example.com"}

    status, page1 = _request(
        "GET",
        f"{live_server}/api/v1/projects/{project_id}/items?limit=5",
        headers=headers,
    )
    assert status == 200
    assert len(page1["items"]) == 5
    assert page1["next_cursor"]

    status, page2 = _request(
        "GET",
        f"{live_server}/api/v1/projects/{project_id}/items?limit=5&cursor={page1['next_cursor']}",
        headers=headers,
    )
    assert status == 200
    assert page2["items"][0]["item_id"] != page1["items"][0]["item_id"]

    item_id = page1["items"][0]["item_id"]
    status, single = _request(
        "GET",
        f"{live_server}/api/v1/projects/{project_id}/items/{item_id}",
        headers=headers,
    )
    assert status == 200
    assert single["item_id"] == item_id


def test_http_event_ingest_idempotency_and_resume(live_server: str):
    project_id = _project_id()
    item_id = _first_item_id()
    headers = {"x-user-id": "reviewer@example.com"}

    event_id = str(uuid.uuid4())
    payload = {
        "client_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "events": [
            {
                "event_id": event_id,
                "item_id": item_id,
                "decision_id": "pass",
                "note": "ok",
                "ts_client": 1739472000000,
            }
        ],
    }

    status, first = _request(
        "POST",
        f"{live_server}/api/v1/projects/{project_id}/events",
        headers=headers,
        body=payload,
    )
    assert status == 200
    assert first["accepted"] == 1

    status, second = _request(
        "POST",
        f"{live_server}/api/v1/projects/{project_id}/events",
        headers=headers,
        body=payload,
    )
    assert status == 200
    assert second["duplicate"] == 1

    status, decisions = _request(
        "GET",
        f"{live_server}/api/v1/projects/{project_id}/decisions",
        headers=headers,
    )
    assert status == 200
    assert any(d["event_id"] == event_id for d in decisions["decisions"])


def test_http_export_create_list_get(live_server: str):
    project_id = _project_id()
    headers = {"x-user-id": "reviewer@example.com"}

    status, created = _request(
        "POST",
        f"{live_server}/api/v1/projects/{project_id}/exports",
        headers=headers,
        body={
            "mode": "labels_only",
            "label_policy": "latest_per_user",
            "format": "jsonl",
            "filters": {},
            "include_fields": ["item_id", "external_id", "decision_id", "note", "ts_server"],
        },
    )
    assert status == 200
    export_id = created["export_id"]

    status, listing = _request(
        "GET",
        f"{live_server}/api/v1/projects/{project_id}/exports",
        headers=headers,
    )
    assert status == 200
    assert any(e["export_id"] == export_id for e in listing["exports"])

    status, fetched = _request(
        "GET",
        f"{live_server}/api/v1/projects/{project_id}/exports/{export_id}",
        headers=headers,
    )
    assert status == 200
    assert fetched["status"] == "ready"
    assert fetched["manifest"]["row_count"] >= 0
