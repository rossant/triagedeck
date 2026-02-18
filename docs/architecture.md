# triagedeck Architecture (Initial Local Reference)

## Runtime Components

- `fastapi_server/`: API, auth, DB access, export flow.
- `client/`: lightweight static local shell.
- `scripts/`: seed and smoke-check scripts.
- `data/`: sqlite DB and local export artifacts.

## Local-First Execution

- API runs on `http://127.0.0.1:8000`.
- Client runs via static server on `http://127.0.0.1:8080`.
- Default auth model: pass `x-user-id` header.
- Default DB: SQLite at `data/triagedeck.db`.

## Data Flow

1. Client fetches project/config/items.
2. Client posts decision events in batches.
3. API writes immutable `decision_event` then updates `decision_latest` by deterministic ordering.
4. Export jobs produce dataset artifacts + manifest in `data/exports`.

## Scope Status

This implementation is a runnable baseline for Phase 1, not full feature-complete parity yet.

## Next Steps

1. API parity hardening:
   - align remaining FastAPI + Django adapter behavior with `docs/spec.md`
   - enforce export limit/concurrency and cursor-expiry edge cases uniformly
2. Export pipeline hardening:
   - move from baseline export behavior to reproducible artifact pipeline with stronger lifecycle controls
3. Client resilience verification:
   - add deeper browser/offline replay test coverage and URL-state recovery checks
4. Performance gate enforcement:
   - codify and run p95 latency gates required by Phase 1 exit criteria
