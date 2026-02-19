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

Completed:
1. API parity hardening across FastAPI and Django adapter for cursor validation, export constraints, and role-scoped export visibility.
2. Export pipeline hardening baseline with deterministic artifact generation, reproducible manifests, expiry cleanup, and audit hooks.
3. Client resilience verification coverage for offline queue replay and URL state round-trip recovery.
4. Performance gate enforcement via automated latency tests and `just test-perf`.
5. Structured observability baseline:
   - FastAPI and Django metrics snapshots exposed at `/metrics`
   - Structured logging and in-memory latency/counter instrumentation for ingest/export flows

Next:
1. Expand contract tests for lifecycle edge cases and replay determinism.
2. Tighten local/CI gate documentation and policies around environment-dependent skips.
3. Extend observability depth with additional per-route/per-error dimensions and dashboards.
