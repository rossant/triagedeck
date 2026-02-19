# triagedeck

## Quick Start (local)

- `just bootstrap`
- `just dev`

API: `http://127.0.0.1:8000`
Client: `http://127.0.0.1:8080`

Auth for local testing: set request header `x-user-id` to one of:

- `admin@example.com`
- `reviewer@example.com`
- `viewer@example.com`

Client keyboard shortcuts:

- `Left`/`Right`: previous/next item
- `P`: PASS decision
- `F`: FAIL decision
- `R`: force sync

Client state tools:

- `Export Local State`: downloads local browser state JSON
- `Import Local State`: restores exported JSON (schema + project validated)
- `Crash Replay Test`: simulates restart/replay and verifies pending queue flush

## Current Status

Implemented:

- FastAPI reference backend with core Phase-1 endpoints:
  - projects/config/items/item/url
  - events ingest + decisions resume
  - exports create/list/get/cancel
- SQLite schema managed by Alembic (`alembic/` + `0001_initial_schema`).
- Local-first browser client with:
  - IndexedDB queue/state (`pending_events`, `local_decisions`, `last_position`, `sync_state`)
  - optimistic decisions + sync manager/backoff
  - keyboard navigation/actions
  - local export/import of browser state
  - crash-replay harness
- Django adapter (`django_app`) with models, permissions, urls, and API views including export endpoints.
- Automated tests:
  - FastAPI API tests
  - live HTTP contract tests (auto-skip when sockets are unavailable)
  - browser workflow tests (auto-skip when Playwright/browser/sockets unavailable)
  - Django adapter tests
  - migration smoke tests

Current test baseline in this environment:

- `20 passed, 7 skipped`

Not complete yet:

- Full spec parity across every endpoint/edge case in `docs/spec.md` (remaining hardening and breadth work).
- Full production-grade export artifact pipeline for Django adapter (current implementation is functional baseline).

## Developer Commands (`just`)

- `just bootstrap`
- `just dev`
- `just test`
- `just test-api` (core API tests + live HTTP contract tests with explicit skip reasons)
- `just test-client` (browser workflow tests; skips with reason if Playwright/browser/socket unavailable)
- `just lint`
- `just fmt`
- `just check`
- `just db-upgrade`
- `just db-reset`
- `just db-migrate <name>` (create Alembic revision)
- `just seed`
- `just export-smoke`

Playwright setup (for `just test-client`):

- `uv add --dev playwright`
- `uv run playwright install chromium`

## Manual Testing (local)

1. Bootstrap and run

- `just bootstrap`
- `just dev`
- Open `http://127.0.0.1:8080`

2. UI smoke test

- Use `reviewer@example.com`, click `Load`.
- Press `P` / `F` to create decisions.
- Navigate with `Left` / `Right`.
- Click `Export Local State`, then re-import with `Import Local State`.
- Click `Crash Replay Test` and confirm success in the log.

3. Offline replay test (browser)

- In DevTools, set Network to `Offline`.
- Press `P`: expect `SYNC_ERROR` and queued count increase.
- Return online, press `R`: expect `SYNC_OK` and queue returns to `0`.

4. API smoke test (terminal)

```bash
PROJECT_ID=$(curl -s -H 'x-user-id: reviewer@example.com' http://127.0.0.1:8000/api/v1/projects | jq -r '.projects[0].project_id')
ITEM_ID=$(curl -s -H 'x-user-id: reviewer@example.com' "http://127.0.0.1:8000/api/v1/projects/$PROJECT_ID/items?limit=1" | jq -r '.items[0].item_id')

curl -s -H 'x-user-id: reviewer@example.com' -H 'content-type: application/json' \
  -d "{\"client_id\":\"$(uuidgen)\",\"session_id\":\"$(uuidgen)\",\"events\":[{\"event_id\":\"$(uuidgen)\",\"item_id\":\"$ITEM_ID\",\"decision_id\":\"pass\",\"note\":\"manual\",\"ts_client\":$(date +%s%3N)}]}" \
  "http://127.0.0.1:8000/api/v1/projects/$PROJECT_ID/events" | jq
```

5. Export API smoke test (terminal)

```bash
EXPORT_ID=$(curl -s -H 'x-user-id: reviewer@example.com' -H 'content-type: application/json' \
  -d '{"mode":"labels_only","label_policy":"latest_per_user","format":"jsonl","filters":{},"include_fields":["item_id","external_id","decision_id","note","ts_server"]}' \
  "http://127.0.0.1:8000/api/v1/projects/$PROJECT_ID/exports" | jq -r '.export_id')

curl -s -H 'x-user-id: reviewer@example.com' "http://127.0.0.1:8000/api/v1/projects/$PROJECT_ID/exports/$EXPORT_ID" | jq
```

6. Metrics check

- `curl -s http://127.0.0.1:8000/metrics | jq`
