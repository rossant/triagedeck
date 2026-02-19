# Phase 1 Implementation Checklist

Source of truth: `docs/spec.md` v1.3 and `docs/api.md`.

## Immediate Next Steps (Implementation Order)

Completed in codebase:
- API parity hardening across FastAPI + Django adapter (cursor validation, export limits, listing visibility parity, error semantics).
- Export pipeline hardening baseline (deterministic artifacts/manifests, storage abstraction, expiry cleanup hooks, audit hooks).
- Client resilience test expansion (offline queue replay + URL round-trip browser tests).
- Performance gate automation (local decision latency and sync ack p95 tests + `just test-perf`).
- Structured observability baseline (metrics endpoint + ingest/export counters/latencies + structured logs).

Now prioritize:
1. Contract depth expansion:
   - additional edge-case contract tests for cursor tampering, export lifecycle transitions, and deterministic replay convergence
2. CI-equivalent local gate tightening:
   - ensure `just check` is the single strict pre-merge gate and document skip policies for environment-constrained tests
3. Observability depth expansion:
   - add richer dimensions (error codes, role, endpoint class) and dashboard-ready export

## 1. Backend Data Model

- [ ] Create tables: `organization`, `organization_membership`, `project`, `item`, `item_variant`.
- [ ] Create tables: `decision_event`, `decision_latest`.
- [ ] Create table: `export_job`.
- [ ] Add soft-delete fields (`deleted_at`) for `project` and `item`.
- [ ] Add `ts_client_effective` in event/latest tables.
- [ ] Add unique constraints:
  - [ ] `(project_id, user_id, event_id)` on `decision_event`.
  - [ ] `(project_id, user_id, item_id)` on `decision_latest`.
  - [ ] `(item_id, variant_key)` on `item_variant`.

## 2. Backend Indexes and Limits

- [ ] Add indexes:
  - [ ] `(project_id, sort_key)` on `item`.
  - [ ] `(item_id, sort_order, variant_key)` on `item_variant`.
  - [ ] `(project_id, user_id, item_id)` on `decision_latest`.
  - [ ] `(project_id, user_id, event_id)` on `decision_event`.
- [ ] Enforce export limits:
  - [ ] max concurrent export jobs/user = `2`.
  - [ ] max rows/job = `1,000,000`.
  - [ ] max file size/job = `5 GB`.
  - [ ] TTL for ready exports = `7 days`.

## 3. Auth and Authorization

- [ ] Implement project-scoped auth for every endpoint.
- [ ] Enforce role matrix (`admin`, `reviewer`, `viewer`).
- [ ] Enforce export creation default permission (`reviewer`/`admin`) with optional org policy override.
- [ ] Enforce export download policy (creator + admin by default).
- [ ] Return `404` for non-membership to prevent enumeration.

## 4. Item and Config APIs

- [ ] `GET /api/v1/projects`
- [ ] `GET /api/v1/projects/{project_id}/config`
- [ ] `GET /api/v1/projects/{project_id}/items` with cursor + limits + variant ordering.
- [ ] `GET /api/v1/projects/{project_id}/items/{item_id}` (deep-link hydration).
- [ ] `GET /api/v1/projects/{project_id}/items/{item_id}/url` with optional `variant_key`.

## 5. Decision APIs and Sync Semantics

- [ ] `POST /api/v1/projects/{project_id}/events` (batch, idempotent, partial success).
- [ ] `GET /api/v1/projects/{project_id}/decisions` (current user latest state).
- [ ] Implement deterministic event ordering:
  - [ ] `ts_client_effective` desc
  - [ ] `ts_server` desc
  - [ ] `event_id` desc
- [ ] Implement skew-window clamping for `ts_client` (+/-24h default).

## 6. External ML Export APIs

- [ ] `POST /api/v1/projects/{project_id}/exports`
- [ ] `GET /api/v1/projects/{project_id}/exports/{export_id}`
- [ ] `GET /api/v1/projects/{project_id}/exports`
- [ ] `DELETE /api/v1/projects/{project_id}/exports/{export_id}`
- [ ] Enforce `include_fields` allowlist from `project.config_json.export_allowlist` (fallback global).
- [ ] Produce package with dataset file + `manifest.json`.
- [ ] Compute and store manifest fields (`snapshot_at`, `row_count`, `sha256`, etc.).
- [ ] Ensure exports use logical URIs by default (not signed URLs).

## 7. Client Core (Phase 1)

- [ ] Implement `App`, `Router`, `URLStateManager`, `ItemLoader`, `RendererRegistry`, `DecisionController`, `SyncManager`, `IndexedDBStore`.
- [ ] IndexedDB stores:
  - [ ] `pending_events`
  - [ ] `local_decisions`
  - [ ] `last_position`
  - [ ] `sync_state`
- [ ] Ensure event is persisted before optimistic UI update.
- [ ] Reconcile optimistic and server state with ordering rules.

## 8. Client UX and URL State

- [ ] Implement URL as canonical view state.
- [ ] Update URL on view changes (`replace` default, `push` on item navigation).
- [ ] Validate/clamp params:
  - [ ] `reveal` `[0,100]` default `50`
  - [ ] `zoom` `[0.1,20]` default `1.0`
  - [ ] `pan_x` `[-1,1]` default `0`
  - [ ] `pan_y` `[-1,1]` default `0`
- [ ] Implement keyboard-only critical paths.
- [ ] Implement local browser export/import flow.
- [ ] Implement external ML export UI flow (create, monitor, download, cancel, retry).

## 9. Sync and Resilience

- [ ] Sync states: `SYNC_OK`, `SYNCING`, `SYNC_ERROR`.
- [ ] Banner shows queued count + last successful sync timestamp.
- [ ] Backoff: base 500ms, max 30s, full jitter, reset after success.
- [ ] Crash-recovery path with pending queue replay.

## 10. Observability

- [ ] Structured logs with request id + project/user/session/event ids where relevant.
- [ ] Metrics:
  - [ ] event ingest rate
  - [ ] duplicate/rejected rates
  - [ ] sync p95 latency
  - [ ] export duration/failure/bytes

## 11. Contract and E2E Tests

- [ ] Duplicate event replay idempotency.
- [ ] Out-of-order event arrival convergence.
- [ ] Invalid/expired cursor handling.
- [ ] Role enforcement and visibility behavior.
- [ ] Signed URL expiry + refresh.
- [ ] URL round-trip restore (including compare params).
- [ ] Deep link load by item outside current page.
- [ ] Local export/import round-trip with pending events.
- [ ] Export allowlist enforcement.
- [ ] Export expiry (`410 export_expired`).
- [ ] Export cancel semantics (`409` if ready, idempotent otherwise).

## 12. Phase 1 Exit Gates

- [ ] p95 local decision UI latency < 50ms.
- [ ] p95 online sync ack latency < 2s.
- [ ] No decision loss in crash-recovery test.
- [ ] Local export/import round-trip without data loss.
- [ ] External ML export reproducibility: deterministic row_count + sha256 for same snapshot/filter.

## 13. Developer Operations (`just`)

- [ ] Add a root `justfile` and make it the primary local workflow entrypoint.
- [ ] `just bootstrap` installs dependencies and initializes local configuration.
- [ ] `just dev` runs the local FastAPI server and client for end-to-end local testing.
- [ ] `just test` runs full automated checks.
- [ ] `just test-api` runs backend/API and contract tests.
- [ ] `just test-client` runs client tests.
- [ ] `just lint` runs static analysis checks.
- [ ] `just fmt` formats code.
- [ ] `just check` runs formatting, linting, and tests as a CI-equivalent local gate.
- [ ] `just db-migrate` creates database migrations.
- [ ] `just db-upgrade` applies migrations to the local database.
- [ ] `just db-reset` recreates local database state for clean-room testing.
- [ ] `just seed` loads deterministic local demo data.
- [ ] `just clean` removes generated artifacts and caches.
- [ ] `just export-smoke` performs a quick local export-job smoke test.
