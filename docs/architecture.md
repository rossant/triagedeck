# triagedeck Architecture (v1.3)

This document describes the implementation architecture for `docs/spec.md` v1.3 and `docs/api.md`.

## 1. Goals

- Preserve offline-first review reliability with deterministic event reconciliation.
- Keep decisioning item-centric, with optional item variants for display.
- Support reproducible export for external ML without in-product ML execution.
- Keep backend pluggable for Django integration and standalone FastAPI.

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
  - Project + Item + Decision APIs
  - Export APIs
        |
        +--> StorageResolver (logical URI -> browser-usable URL)
        |
        +--> DB (projects/items/variants/events/latest/export_jobs)
        |
        +--> Export Worker (async snapshot packaging)
```

## 3. Backend Components

## 3.1 API Layer

Responsibilities:

- Authentication and membership validation.
- Role authorization.
- Request validation and response shaping.
- Cursor encoding/decoding.
- Idempotent event ingestion contract.

## 3.2 Domain Services

- `DecisionIngestService`
  - validates events.
  - persists `decision_event`.
  - computes and applies `decision_latest`.
- `DecisionQueryService`
  - serves current-user latest decisions with cursor pagination.
- `ItemQueryService`
  - serves cursor item lists + variants.
  - serves single-item deep-link hydration.
- `ExportService`
  - creates/lists/gets/cancels export jobs.
  - enforces allowlist and export limits.
- `StorageResolverService`
  - resolves signed/stream URLs for item or variant media.

## 3.3 Export Worker

Async worker process (or background task subsystem) that:

- transitions `export_job` status: `queued -> running -> ready/failed/expired`.
- snapshots eligible rows at job start.
- writes dataset + `manifest.json`.
- computes `sha256`.
- writes `file_uri` and `expires_at`.
- enforces row/size limits.

## 4. Data Model and Invariants

Core entities:

- `project`, `item`, `item_variant`, `decision_event`, `decision_latest`, `export_job`.

Critical invariants:

- `decision_event` is append-only and immutable.
- event idempotency key: `(project_id, user_id, event_id)`.
- latest state uniqueness: `(project_id, user_id, item_id)`.
- variant uniqueness: `(item_id, variant_key)`.
- decisions are item-level, never variant-level.
- soft-deleted `project/item` excluded from default queries.

## 5. Decision Consistency Model

For same `(project_id, user_id, item_id)`, winning event order:

1. highest `ts_client_effective`
2. tie-break highest `ts_server`
3. tie-break highest lexicographic `event_id`

`ts_client` handling:

- validate against skew window (+/-24h default).
- clamp to window for `ts_client_effective`.
- persist both original `ts_client` and `ts_client_effective`.

Write path rule:

- persist event first, then update latest.

## 6. API Read/Write Flows

## 6.1 Decision Ingest

1. Client submits batch to `POST /projects/{project_id}/events`.
2. API authenticates and validates each event.
3. For each event:
   - if duplicate idempotency key => `duplicate`.
   - else persist event + recompute latest winner.
4. Return per-event results with partial success semantics.

## 6.2 Resume Decisions

1. Client calls `GET /projects/{project_id}/decisions?cursor&limit`.
2. API reads `decision_latest` for `request.user.id`.
3. API returns ordered page + `next_cursor`.

## 6.3 URL Deep-Link Hydration

1. Client parses URL canonical state (`item`, variants, compare, reveal, zoom/pan).
2. If target item missing from in-memory page, call `GET /projects/{project_id}/items/{item_id}`.
3. Render state and clamp/fallback invalid params.

## 6.4 External ML Export

1. User creates job via `POST /projects/{project_id}/exports`.
2. API validates role, filters, and allowlisted fields.
3. Job enqueued in `export_job`.
4. Worker builds snapshot package.
5. Client polls `GET /exports/{id}` until `ready`.
6. Client downloads artifact via short-lived URL.

## 7. Client Architecture

## 7.1 State Domains

- `server_state`: items, decisions, config.
- `local_sync_state`: pending events, sync status, retry metadata.
- `view_state`: canonical URL params (item/variant/compare/reveal/zoom/pan).

## 7.2 URLStateManager

Responsibilities:

- Parse URL on load.
- Validate/clamp bounds.
- Apply defaults.
- Write updates with:
  - history `replace` for local view changes.
  - history `push` for item navigation.
- Prevent write/read loops via change origin tagging.

## 7.3 SyncManager

- Sends pending events in batches (max 200).
- Exponential backoff (500ms base, 30s max, full jitter).
- Resets backoff on success.
- Maintains banner state: `SYNC_OK`, `SYNCING`, `SYNC_ERROR`.

## 7.4 Renderer Layer

- `RendererRegistry` routes by media type.
- Image renderer supports:
  - variant switching (up/down + wheel).
  - compare mode (2 variants).
  - reveal divider (0..100 with keyboard nudge).
- Review hotkeys remain responsive during rendering actions.

## 8. Storage and URL Strategy

- DB stores logical URIs.
- API resolves browser-usable URLs at read time.
- Signed URL TTL default 15 min.
- Refresh endpoint supports optional `variant_key`.
- URLs in browser query params must never contain signed URLs or credentials.

## 9. Export Architecture for External ML

Output package:

- `dataset.<ext>`
- `manifest.json`

Manifest minimum:

- `snapshot_at`, `project_id`, `decision_schema_version`,
- `label_policy`, `filters`, `row_count`, `sha256`.

Security/governance:

- allowlist-driven field inclusion.
- audit log each export request.
- access policy for job creation/download.
- artifact TTL cleanup job marks stale artifacts `expired`.

## 10. Operational Concerns

## 10.1 Background Jobs

- Export worker queue.
- Expiry sweeper for export artifacts.

## 10.2 Observability

Logs:

- include request id + project/user/session/event/export ids where available.

Metrics:

- decision ingest throughput.
- duplicate/reject rates.
- sync p95 round-trip.
- export duration/failure/bytes.

## 10.3 Scalability

- cursor pagination only.
- indexed access patterns per spec.
- bounded batch/event sizes.
- bounded export concurrency and artifact size.

## 11. Failure Modes and Recovery

- Duplicate event replay: absorbed via idempotency key.
- Out-of-order event arrival: converges via deterministic ordering.
- Client crash while offline: replay from IndexedDB pending queue.
- Expired media URL: refresh via item URL endpoint.
- Export job failure: visible as `failed`; retry creates a new job.
- Export cancellation: idempotent delete operation.

## 12. Implementation Modes

## 12.1 Django Integration

- app module: models/views/urls/permissions.
- uses existing `AUTH_USER_MODEL` and sessions.
- migrations applied into existing DB.

## 12.2 FastAPI Standalone

- SQLAlchemy models + Alembic.
- token/header auth adapter.
- same endpoint contract and behavior as Django mode.

## 13. Phase 1 Boundaries

In:

- image-first review.
- decision schema + offline sync.
- URL canonical state.
- local browser export/import.
- external ML export jobs and artifact download.

Out:

- in-product ML model training/serving/auto-decisioning.
- advanced adjudication workflows.
- plugin-heavy domain renderers.
