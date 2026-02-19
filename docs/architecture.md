# triagedeck Architecture (v1.3)

This document defines the implementation architecture for `docs/spec.md` v1.3 and `docs/api.md`.

## 1. Goals

- Preserve offline-first review with deterministic reconciliation.
- Keep decisions item-centric, while allowing variant-specific rendering.
- Support reproducible export for external ML without in-product ML execution.
- Keep backend implementation portable between Django and standalone FastAPI.

## 2. System Context

```text
Browser Client
  - Router + URLStateManager
  - RendererRegistry (image/video/pdf)
  - DecisionController + SyncManager
  - IndexedDBStore
        |
        v
REST API (/api/v1)
  - AuthN/AuthZ
  - Project + Item + Decision endpoints
  - Export endpoints
        |
        +--> StorageResolver (logical URI -> browser URL)
        |
        +--> DB (project/item/variant/event/latest/export_job)
        |
        +--> Export Worker (async snapshot packaging)
```

## 3. Backend Architecture

### 3.1 API Layer

Responsibilities:

- Authenticate users and validate project membership.
- Authorize actions by role and scope.
- Validate requests and normalize response shape.
- Encode/decode cursors.
- Enforce idempotent decision ingest semantics.

Current status:

- FastAPI and Django adapters follow the same API contract for cursor validation, export constraints, and role-scoped export visibility.
- Export pipeline provides deterministic artifact generation, reproducible manifests, expiry cleanup, and audit hooks.
- Offline replay and URL state round-trip resilience are covered by automated tests.
- Performance gates are enforced through latency tests and `just test-perf`.
- Metrics are exposed at `/metrics`; ingest/export flows emit structured logs and latency/counter signals.

Planned improvements:

- Expand contract tests for lifecycle edge cases and replay determinism.
- Tighten CI/local gate policy around environment-dependent test skips.
- Add route-level and error-level observability dimensions and dashboard coverage.

### 3.2 Domain Services

- `DecisionIngestService`: validates events, appends `decision_event`, recomputes and upserts `decision_latest`.
- `DecisionQueryService`: serves current-user latest decisions with cursor pagination.
- `ItemQueryService`: serves item pages with variants and single-item deep-link hydration.
- `ExportService`: creates, lists, fetches, and cancels export jobs; enforces allowlist and export limits.
- `StorageResolverService`: resolves item/variant media into browser-usable signed or stream URLs.

### 3.3 Export Worker

Asynchronous worker (process or task subsystem) that:

- Transitions `export_job` state: `queued -> running -> ready|failed|expired`.
- Snapshots eligible rows at job start.
- Writes dataset payload and `manifest.json`.
- Computes artifact `sha256`.
- Persists `file_uri` and `expires_at`.
- Enforces row and artifact-size limits.

## 4. Data Model and Invariants

Core entities:

- `project`
- `item`
- `item_variant`
- `decision_event`
- `decision_latest`
- `export_job`

Critical invariants:

- `decision_event` is append-only and immutable.
- Event idempotency key is `(project_id, user_id, event_id)`.
- Latest row uniqueness is `(project_id, user_id, item_id)`.
- Variant uniqueness is `(item_id, variant_key)`.
- Decisions are item-level, never variant-level.
- Soft-deleted `project` or `item` rows are excluded from default reads.

## 5. Decision Consistency Model

For a fixed `(project_id, user_id, item_id)`, winner ordering is:

1. Highest `ts_client_effective`
2. Then highest `ts_server`
3. Then highest lexicographic `event_id`

`ts_client` handling:

- Validate against skew window (default `+/-24h`).
- Clamp to window as `ts_client_effective`.
- Persist both `ts_client` and `ts_client_effective`.

Write-order rule:

- Persist event first, then recompute/update latest state.

## 6. API Flows

### 6.1 Decision Ingest

1. Client submits a batch to `POST /projects/{project_id}/events`.
2. API authenticates caller and validates each event.
3. API checks idempotency key `(project_id, user_id, event_id)` for each event.
4. Duplicate events return `duplicate`.
5. Non-duplicate events are appended and latest winners are recomputed.
6. API returns per-event results with partial-success semantics.

### 6.2 Resume Decisions

1. Client calls `GET /projects/{project_id}/decisions?cursor&limit`.
2. API reads `decision_latest` for the requesting user.
3. API returns ordered rows plus `next_cursor`.

### 6.3 URL Deep-Link Hydration

1. Client parses canonical URL state (`item`, variants, compare, reveal, zoom/pan).
2. If target item is missing locally, client calls `GET /projects/{project_id}/items/{item_id}`.
3. Client renders resolved state and clamps/falls back invalid parameters.

### 6.4 External ML Export

1. User creates a job with `POST /projects/{project_id}/exports`.
2. API validates role, filters, and allowlisted fields.
3. API enqueues a row in `export_job`.
4. Worker builds a consistent snapshot package.
5. Client polls `GET /exports/{id}` until state is `ready`.
6. Client downloads artifact through a short-lived URL.

## 7. Client Architecture

### 7.1 State Domains

- `server_state`: items, decisions, server-provided config.
- `local_sync_state`: pending events, retry metadata, sync status.
- `view_state`: canonical URL params (`item`, `variant`, `compare`, `reveal`, `zoom`, `pan`).

### 7.2 URLStateManager

Responsibilities:

- Parse URL state at load.
- Validate bounds and apply defaults.
- Update history with `replace` for local view changes.
- Update history with `push` for item navigation.
- Prevent write/read loops with origin tagging.

### 7.3 SyncManager

- Sends pending events in bounded batches (max 200).
- Uses exponential backoff (500 ms base, 30 s max, full jitter).
- Resets backoff after successful flush.
- Maintains user-visible sync state: `SYNC_OK`, `SYNCING`, `SYNC_ERROR`.

### 7.4 Renderer Layer

- `RendererRegistry` dispatches by media type.
- Image renderer supports variant switching (keyboard and wheel), two-variant compare mode, and reveal divider (`0..100`) with keyboard nudging.
- Review hotkeys remain responsive during rendering operations.

## 8. Storage and URL Strategy

- Database stores logical media URIs, never embed credentials in persistent fields.
- API resolves logical URIs into browser-usable URLs at read time.
- Signed URL TTL default is 15 minutes.
- URL refresh endpoint supports optional `variant_key`.
- Browser query params must never contain signed URLs or credentials.

## 9. External ML Export Package

Output files:

- `dataset.<ext>`
- `manifest.json`

Manifest minimum fields:

- `snapshot_at`
- `project_id`
- `decision_schema_version`
- `label_policy`
- `filters`
- `row_count`
- `sha256`

Security and governance:

- Allowlist-driven field inclusion.
- Audit log per export request.
- Access policy on create/download operations.
- TTL cleanup marks stale artifacts as `expired`.

## 10. Operations

### 10.1 Background Jobs

- Export worker queue.
- Expiry sweeper for stale export artifacts.

### 10.2 Observability

Logs:

- Include request ID plus project/user/session/event/export IDs where available.

Metrics:

- Decision ingest throughput.
- Duplicate/reject rates.
- Sync round-trip p95.
- Export duration, failure count, and artifact bytes.

### 10.3 Scalability Constraints

- Cursor pagination only.
- Indexed access patterns required by spec.
- Bounded batch size and event payload size.
- Bounded export concurrency and artifact size.

## 11. Failure Modes and Recovery

- Duplicate event replay is absorbed by idempotency key.
- Out-of-order event arrival converges through deterministic winner ordering.
- Offline client crash recovers by replaying IndexedDB pending queue.
- Expired media URLs recover via URL refresh endpoint.
- Failed export jobs remain visible as `failed`; retries create new jobs.
- Export cancellation is idempotent.

## 12. Deployment Modes

### 12.1 Django Integration

- Django app module with models/views/urls/permissions.
- Reuses existing `AUTH_USER_MODEL` and session stack.
- Applies migrations in existing database.

### 12.2 FastAPI Standalone

- SQLAlchemy models plus Alembic migrations.
- Token/header auth adapter.
- Same endpoint contract and behavior as Django mode.

## 13. Phase 1 Scope

In scope:

- Image-first review flow.
- Decision schema and offline sync.
- Canonical URL state.
- Local browser export/import.
- External ML export jobs and artifact download.

Out of scope:

- In-product model training/serving/auto-decisioning.
- Advanced adjudication workflows.
- Plugin-heavy domain renderer ecosystem.
