from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from fastapi_server.db import init_db
from scripts.seed import main as seed_main

ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT / "client"


def _free_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])
    except PermissionError as exc:
        pytest.skip(f"Browser tests skipped: socket operations are blocked ({exc})")


def _wait_http(url: str, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=2):
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}")


@pytest.fixture(scope="module")
def live_stack(tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:
        pytest.skip(f"Browser tests skipped: playwright unavailable ({exc})")

    init_db()
    seed_main()

    api_port = _free_port()
    client_port = _free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    client_url = f"http://127.0.0.1:{client_port}"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    api_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "fastapi_server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    client_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(client_port),
            "--directory",
            str(CLIENT_DIR),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_http(f"{api_url}/health")
        _wait_http(f"{client_url}/index.html")
        yield {
            "api_url": api_url,
            "client_url": client_url,
            "tmp_dir": tmp_path_factory.mktemp("downloads"),
        }
    finally:
        for proc in (client_proc, api_proc):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_client_browser_workflow(live_stack):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Browser tests skipped: chromium launch failed ({exc})")

        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        page.goto(live_stack["client_url"], wait_until="domcontentloaded")
        page.fill("#user", "reviewer@example.com")
        page.click("#reload")

        page.wait_for_selector("#item-title")
        expect(page.locator("#item-title")).not_to_have_text("No item loaded", timeout=15000)

        page.keyboard.press("p")
        expect(page.locator("#log")).to_contain_text("Decision pass saved locally", timeout=10000)

        with page.expect_download(timeout=10000) as dl_info:
            page.click("#export-state")
        download = dl_info.value
        export_path = live_stack["tmp_dir"] / "state.json"
        download.save_as(str(export_path))
        assert export_path.exists()
        assert export_path.stat().st_size > 0

        page.set_input_files("#import-file", str(export_path))
        page.click("#import-state")
        expect(page.locator("#log")).to_contain_text(
            "Local state imported and reconciled",
            timeout=10000,
        )

        page.click("#crash-replay")
        expect(page.locator("#log")).to_contain_text(
            "Crash replay test passed",
            timeout=12000,
        )

        context.close()
        browser.close()
