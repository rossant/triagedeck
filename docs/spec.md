# triagedeck: Generic Media Review System (Open Source)

**Specification v1.3**

---

## 1. Purpose

A lightweight, open-source, keyboard-driven media review system designed for:

* High-throughput **image review (priority use case)**
* Optional **video and PDF support**
* Customizable decision sets (not limited to PASS/FAIL)
* Strong offline robustness and data integrity
* Full local browser export for backup/handover
* Reproducible label export for external ML workflows
* Minimal JavaScript dependencies
* Pluggable backend architecture
* Integration into existing Django servers
* Standalone FastAPI reference implementation

This system is **not** an annotation platform and does not support bounding boxes, segmentation, or labeling workflows.

---

## 2. Core Principles

1. **Image-first design**
2. **Offline-first, event-sourced architecture**
3. **Minimal dependencies (vanilla JS preferred)**
4. **Pluggable backend contract**
5. **Framework-agnostic API**
6. **Extensible media types**
7. **Extensible storage backends**
8. **Extensible decision schemas**
9. **Strong sync feedback and integrity guarantees**

---

## 3. Scope

### Supported Media Types

* `image` (primary)
* `video` (playback only, no annotation)
* `pdf` (document-level review)
* `other` (extensible renderer plugin interface)

---

## 4. System Architecture

```
Browser Client
    ↓
REST API (framework-agnostic)
    ↓
Export Service (dataset snapshots)
    ↓
Storage Resolver Layer
    ↓
Database + Object Storage
```

### Layers

| Layer            | Responsibility                                  |
| ---------------- | ----------------------------------------------- |
| Client           | Rendering, navigation, decisions, offline queue |
| API              | Authentication, authorization, data validation  |
| Export Service   | Filtered dataset snapshot and packaging for ML  |
| Storage Resolver | Converts logical item to usable URI             |
| DB               | Projects, items, decisions, events              |
| Object Storage   | Images/videos/PDFs (local/S3/etc)               |

---

## 5. Core Domain Model

### 5.1 Organization (optional but recommended)

```
organization
  id
  name
  created_at
```

### 5.2 Users

User management may be external (Django auth, OAuth, etc).

Backend must expose:

```
request.user.id
request.user.email
```

### 5.3 Roles (Global)

Global roles (organization-wide):

* `admin`
* `reviewer`
* `viewer`

Stored as:

```
organization_membership
  organization_id
  user_id
  role
```

Project-level roles are optional.

---

### 5.4 Project

Logical grouping of media items.

```
project
  id
  organization_id
  name
  slug
  created_at
  deleted_at
  decision_schema_json
  config_json
```

---

### 5.5 Item

```
item
  id
  project_id
  external_id
  media_type   # image | video | pdf | other
  uri          # logical URI (not necessarily browser-ready)
  sort_key     # deterministic ordering
  metadata_json
  created_at
  deleted_at
```

Important:

* `external_id` must be stable
* `sort_key` indexed for fast cursor pagination
* Decisions are always scoped to `item` (not to variant)

---

### 5.6 Item Variant (optional per item, recommended for image projects)

```
item_variant
  id
  item_id
  variant_key       # e.g. before | after | raw | processed
  label
  uri               # logical URI for this variant
  sort_order
  metadata_json
  created_at
```

Constraints:

* Unique `(item_id, variant_key)`
* Ordering defaults to `(sort_order ASC, variant_key ASC)`
* `item_variant` rows are soft-deleted when parent `item` is soft-deleted

---

### 5.7 Decision Event (append-only)

```
decision_event
  id
  project_id
  user_id
  event_id          # client-generated UUID
  item_id
  decision_id
  note
  ts_client
  ts_client_effective
  ts_server
```

Unique constraint:

```
(project_id, user_id, event_id)
```

---

### 5.8 Latest Decision (materialized state)

```
decision_latest
  project_id
  user_id
  item_id
  event_id
  decision_id
  note
  ts_client
  ts_client_effective
  ts_server
```

Unique constraint:

```
(project_id, user_id, item_id)
```

---

### 5.9 Event Ordering and Conflict Resolution

`decision_latest` is derived from `decision_event` with deterministic ordering:

1. Highest `ts_client_effective` wins
2. Tie-breaker: highest `ts_server` wins
3. Final tie-breaker: lexicographically highest `event_id` wins

Rules:

* Server always stores immutable `decision_event` rows first, then updates `decision_latest`
* `decision_latest` is per `(project_id, user_id, item_id)` and only compares events from the same user
* Out-of-order delivery must converge to the same `decision_latest` result
* Server validates `ts_client` against a configurable skew window (default: +/-24h from server time)
* If `ts_client` is outside the skew window, server accepts the event and computes `ts_client_effective` by clamping `ts_client` to the skew window at ingest time
* Server persists both original `ts_client` and computed `ts_client_effective`; ordering logic must use `ts_client_effective`

---

### 5.10 Export Job (External ML Dataset Snapshot)

```
export_job
  id
  project_id
  requested_by_user_id
  status            # queued | running | ready | failed | expired
  mode              # labels_only | labels_plus_unlabeled
  label_policy      # latest_per_user
  format            # jsonl | csv | parquet
  filters_json
  manifest_json
  file_uri
  expires_at
  created_at
  completed_at
```

Rules:

* Export jobs are immutable once `ready`
* Export output must include a machine-readable manifest for reproducibility
* Export output must never contain auth tokens, cookies, or raw storage credentials

---

## 6. Decision Schema

Each project defines:

```json
{
  "version": 1,
  "choices": [
    {"id": "pass", "label": "PASS", "hotkey": "p"},
    {"id": "fail", "label": "FAIL", "hotkey": "f"}
  ],
  "allow_notes": true
}
```

Client loads this from:

```
GET /api/projects/{project_id}/config
```

Schema constraints:

* `choices[].id`: required, unique, regex `^[A-Za-z0-9._-]{1,64}$`
* `choices[].label`: required, max 64 chars
* `choices[].hotkey`: optional, single key, unique case-insensitive within the schema
* `allow_notes`: boolean

Schema evolution:

* `version` is monotonically increasing per project
* Existing `decision_event` rows are immutable and remain valid historically
* A schema update may remove or rename choices only for future events
* If a choice is retired, prior events using that choice must still render correctly in history/resume APIs

---

## 7. API Specification

All endpoints are authenticated.

Base path:

* API is versioned at `/api/v1`
* Path examples below omit `/v1` for readability

Common conventions:

* Time fields are Unix epoch milliseconds
* UUID fields are RFC 4122 strings
* Cursor params are opaque and must not be interpreted by clients
* Standard error shape:

```json
{
  "error": {
    "code": "invalid_cursor",
    "message": "Cursor is invalid or expired",
    "details": {}
  }
}
```

Standard error codes:

* `400 bad_request`
* `401 unauthorized`
* `403 forbidden`
* `404 not_found`
* `409 conflict`
* `410 gone`
* `422 validation_error`
* `429 rate_limited`
* `500 internal_error`

---

### 7.1 List Projects

```
GET /api/projects
```

Returns projects visible to user.

---

### 7.2 Get Project Config

```
GET /api/projects/{project_id}/config
```

Returns:

```json
{
  "project": {...},
  "decision_schema": {...},
  "media_types_supported": ["image", "video", "pdf"],
  "variants_enabled": true,
  "variant_navigation_mode": "both",
  "compare_mode_enabled": true,
  "max_compare_variants": 2
}
```

Rules:

* `variant_navigation_mode` values: `horizontal`, `vertical`, `both`
* For v1.3 with compare mode, `max_compare_variants` must be `2`

---

### 7.3 List Items (Cursor-based)

```
GET /api/projects/{project_id}/items?cursor=<opaque>&limit=200
```

Response:

```json
{
  "items": [
    {
      "item_id": "uuid",
      "external_id": "img_0001",
      "media_type": "image",
      "uri": "https://signed-url",
      "variants": [
        {
          "variant_key": "before",
          "label": "Before",
          "uri": "https://signed-url-before",
          "sort_order": 10,
          "metadata": {}
        },
        {
          "variant_key": "after",
          "label": "After",
          "uri": "https://signed-url-after",
          "sort_order": 20,
          "metadata": {}
        }
      ],
      "metadata": {...}
    }
  ],
  "next_cursor": "opaque-or-null"
}
```

Must use indexed cursor (not offset).

Rules:

* Ordering is strict and stable: `(sort_key ASC, item_id ASC)`
* `limit` default is 100, max 200
* Cursor encodes the last seen `(sort_key, item_id)` and expires after 7 days
* Invalid or expired cursor returns `400` with `error.code=invalid_cursor`
* Items with `deleted_at` are excluded
* `variants` must be ordered by `(sort_order ASC, variant_key ASC)`
* For items with no variants, `variants` may be omitted or returned as `[]`

---

### 7.4 Submit Decision Events (Batch)

```
POST /api/projects/{project_id}/events
```

Request:

```json
{
  "client_id": "uuid",
  "session_id": "uuid",
  "events": [
    {
      "event_id": "uuid",
      "item_id": "uuid",
      "decision_id": "pass",
      "note": "",
      "ts_client": 1739472000000
    }
  ]
}
```

Response:

```json
{
  "acked": 12,
  "accepted": 10,
  "duplicate": 2,
  "rejected": 1,
  "server_ts": 1739472100000,
  "results": [
    {"event_id": "uuid-1", "status": "accepted"},
    {"event_id": "uuid-2", "status": "duplicate"},
    {"event_id": "uuid-3", "status": "rejected", "error_code": "invalid_decision_id"}
  ]
}
```

Must be idempotent.

Rules:

* Max `events` per request: 200
* Processing is per-event (partial success allowed); endpoint is not all-or-nothing
* `acked = accepted + duplicate`
* Duplicate is defined by existing `(project_id, user_id, event_id)`
* `item_id` must belong to `project_id`, else event is rejected
* `decision_id` must exist in the active project schema version at ingest time
* `note` max length: 2000 chars
* If `allow_notes=false`, non-empty `note` is rejected
* Server stores `ts_server` and `ts_client_effective` at ingest for each accepted event

---

### 7.5 Fetch Decisions (Resume)

```
GET /api/projects/{project_id}/decisions?cursor=<opaque>
```

Response:

```json
{
  "decisions": [
    {
      "item_id": "uuid",
      "decision_id": "pass",
      "note": "",
      "ts_client": 1739472000000,
      "ts_server": 1739472100000,
      "event_id": "uuid"
    }
  ],
  "next_cursor": "opaque-or-null"
}
```

Rules:

* Returns latest decision state from `decision_latest` for `request.user.id` only
* Ordered by `(ts_server ASC, item_id ASC)` for deterministic resume sync
* Cursor expires after 7 days
* `limit` default is 500, max 2000
* Endpoint supports `?cursor=<opaque>&limit=500`
* Cross-user decision reads are out of scope for v1 and require a dedicated admin endpoint in a future version

---

### 7.6 Refresh Item URL

```
GET /api/projects/{project_id}/items/{item_id}/url
```

Response:

```json
{
  "item_id": "uuid",
  "uri": "https://signed-url",
  "expires_at": 1739472600000
}
```

Rules:

* Use when a signed media URL expires during review
* `item_id` must belong to `project_id`
* Optional query param `variant_key` refreshes the URL for a specific variant
* If `variant_key` is provided, it must exist for `item_id`
* Resolver must not expose storage credentials

---

### 7.7 Get Single Item (Deep Link Support)

```
GET /api/projects/{project_id}/items/{item_id}
```

Response:

```json
{
  "item_id": "uuid",
  "external_id": "img_0001",
  "media_type": "image",
  "uri": "https://signed-url",
  "variants": [
    {
      "variant_key": "before",
      "label": "Before",
      "uri": "https://signed-url-before",
      "sort_order": 10,
      "metadata": {}
    },
    {
      "variant_key": "after",
      "label": "After",
      "uri": "https://signed-url-after",
      "sort_order": 20,
      "metadata": {}
    }
  ],
  "metadata": {}
}
```

Rules:

* Used by client to hydrate URL-driven state when target item is not in current cursor page
* Returns `404` if item is missing, soft-deleted, or inaccessible
* `variants` ordering and optionality match section 7.3

---

### 7.8 Create External ML Export Job

```
POST /api/projects/{project_id}/exports
```

Request:

```json
{
  "mode": "labels_only",
  "label_policy": "latest_per_user",
  "format": "jsonl",
  "filters": {
    "decision_ids": ["pass", "fail"],
    "from_ts": 1739400000000,
    "to_ts": 1739999999000,
    "user_ids": ["uuid-optional"],
    "metadata": {
      "session_id": ["session-01"]
    }
  },
  "include_fields": [
    "item_id",
    "external_id",
    "decision_id",
    "note",
    "ts_server",
    "variant_key",
    "metadata.subject_id",
    "metadata.session_id"
  ]
}
```

Response:

```json
{
  "export_id": "uuid",
  "status": "queued"
}
```

Rules:

* For v1.3, supported `label_policy` is `latest_per_user`
* Default export `format` is `jsonl` when omitted
* Export is snapshot-based at job start time (`snapshot_at` in manifest)
* Default filename pattern: `triagedeck_export_{project_id}_{snapshot_at}.{ext}`
* Export package must include:
  * dataset file (`.jsonl`, `.csv`, or `.parquet`)
  * manifest file (`manifest.json`)
* `include_fields` must be validated against an allowlist
* Field allowlist source of truth is server-side project config (`project.config_json.export_allowlist`) with server global fallback
* Non-allowlisted fields are rejected with `422` and `error.code=field_not_allowlisted`
* By default, export job creation requires `reviewer` or `admin`
* Implementations may allow `viewer` export creation by explicit org policy override

---

### 7.9 Get External ML Export Job

```
GET /api/projects/{project_id}/exports/{export_id}
```

Response:

```json
{
  "export_id": "uuid",
  "status": "ready",
  "format": "jsonl",
  "mode": "labels_only",
  "manifest": {
    "snapshot_at": 1739472100000,
    "project_id": "uuid",
    "decision_schema_version": 3,
    "row_count": 12345,
    "sha256": "..."
  },
  "download_url": "https://signed-export-url",
  "expires_at": 1739558500000
}
```

Rules:

* `download_url` must be short-lived signed URL or authenticated stream endpoint
* Response must include reproducibility manifest metadata
* Download access defaults to export creator and project/org `admin`
* Optional policy may allow `reviewer` download of other users' exports within same project
* Expired jobs return `410` with `error.code=export_expired`

---

### 7.10 List External ML Exports

```
GET /api/projects/{project_id}/exports?cursor=<opaque>&limit=100
```

Rules:

* Ordered by `(created_at DESC, id DESC)`
* `limit` default is 50, max 100
* Access scoped by project membership and role policy

---

### 7.11 Cancel External ML Export Job

```
DELETE /api/projects/{project_id}/exports/{export_id}
```

Rules:

* Cancellation is allowed only for `queued` or `running` jobs
* Cancellation is idempotent
* Cancelled jobs transition to `failed` with `error.code=export_cancelled`
* If job is already `ready`, cancellation request returns `409`

---

## 8. Client Architecture

### 8.1 Core Components

* `App`
* `Router`
* `URLStateManager`
* `ItemLoader`
* `RendererRegistry`
* `DecisionController`
* `SyncManager`
* `IndexedDBStore`

---

### 8.2 IndexedDB Schema

Stores:

* `pending_events`
* `local_decisions`
* `last_position`
* `sync_state`

Event is written before UI update.

Additional client rules:

* Effective decision shown in UI is computed from server decisions plus pending local events using the same ordering rules from section 5.9
* Local unsynced event always appears immediately in UI
* On ack, pending event is removed and `local_decisions` is reconciled from authoritative server ordering
* URL state is canonical for view state and must be restored on load before first paint where possible

---

### 8.3 Sync Manager

States:

* `SYNC_OK` (green)
* `SYNCING` (amber)
* `SYNC_ERROR` (red)

Banner must display:

* number of queued events
* last successful sync timestamp

Retry strategy:

* exponential backoff
* manual retry shortcut

Backoff policy:

* Exponential backoff base 500ms, max 30s, full jitter
* Backoff resets after one successful sync round-trip

---

### 8.4 Local Browser Export/Import (Phase 1)

Client must support exporting all local review state to a downloadable file and importing it later.

Export scope (minimum):

* `pending_events`
* `local_decisions`
* `last_position`
* `sync_state`
* Current URL view state parameters
* Export metadata (`exported_at`, app version, schema version, project ID)

Rules:

* Export format must be JSON (optionally gzip-compressed)
* Export must be initiated locally in-browser; no server round-trip required
* Import must validate schema version and reject incompatible payloads with a clear error
* Import must be idempotent for already-imported events via existing event idempotency rules
* Export/import must not include auth tokens, cookies, or signed media URLs

---

### 8.5 External ML Export UX (Phase 1)

Client must expose a simple export flow for generating server-side dataset snapshots.

Requirements:

* Export wizard with filter selection and field allowlist
* Progress and terminal states (`queued`, `running`, `ready`, `failed`, `expired`)
* One-click manifest download and dataset download
* Cancel action for `queued` and `running` export jobs
* Retry action creates a new export job with same request payload
* Clear warning that model training/inference is out of scope for triagedeck

---

## 9. Media Rendering

### 9.1 Renderer Interface

```js
class Renderer {
  mount(container, item)
  unmount()
  onKey(event)
  prefetch(item)
  setVariant(variantKey)
  setCompareMode(enabled, variantA, variantB)
  setRevealPosition(percent)
}
```

---

### 9.2 Image Renderer

* Single `<img>` or `<canvas>`
* Prefetch next N
* LRU memory cap
* No thousands of DOM nodes
* Must support item variants where configured
* Must support two-variant compare mode with draggable vertical reveal divider

---

### 9.3 Video Renderer

* Native `<video>`
* Keyboard controls:

  * space: play/pause
  * j/l: ±1s
  * shift+j/l: ±5s
  * 0: start
* No annotation layer

---

### 9.4 PDF Renderer

Phase 1:

* Native embed

Phase 2 (optional):

* PDF.js plugin

---

### 9.5 Variant Navigation and Compare Mode

Interaction rules:

* `left/right` navigate previous/next item
* `up/down` navigate previous/next variant in current item
* Mouse wheel navigates variants in current item when pointer is over media viewport
* Compare mode shows exactly 2 variants at once
* Compare mode toggle key: `c`
* Variant cycle key: `v`

Reveal divider behavior:

* Divider is vertical and moves on horizontal axis
* Position range is `0..100` percent of viewport width
* Divider is draggable with pointer input
* Keyboard nudge: `[` moves -1%, `]` moves +1%
* Reset reveal shortcut: `\\` sets position to `50`
* If fewer than 2 variants are available, compare mode must be disabled for that item

Rendering constraints:

* Variant switching should not block decision hotkeys
* Compare drag should target smooth interaction on modern hardware (60fps goal)

---

## 10. Storage Resolver Interface (Backend)

Backend must translate `item.uri` into browser-usable URL.

Interface:

```python
class StorageResolver:
    def resolve(self, item) -> str:
        ...
```

Implementations:

* Local file system
* S3 signed URL
* GCS signed URL
* Custom HTTP backend
* Reverse proxy streaming

Client must never receive raw credentials.

Resolver requirements:

* Default signed URL TTL: 15 minutes (configurable 5 to 60 minutes)
* Resolver must be called at read time (not pre-materialized in DB)
* Server returns `expires_at` where available so client can refresh before playback/view fails

---

## 11. Security Model

* All API routes authenticated
* All routes scoped by project
* Validate item belongs to project
* Use signed URLs for private storage
* Optional reverse-proxy auth integration
* CSRF protection if using cookies

Authorization matrix:

* `admin`: full read/write in org projects
* `reviewer`: read projects/items/config and write events; may create external ML export jobs
* `viewer`: read-only (projects/items/config/decisions), no event writes; export creation only if explicitly enabled by org policy

Resource visibility rules:

* Non-membership returns `404` to avoid project enumeration
* Write attempts without permission return `403`

---

## 12. Django Integration Mode

Provide:

```
media_review/
  models.py
  views.py
  urls.py
  permissions.py
```

Usage:

```
INSTALLED_APPS += ["media_review"]
include("media_review.urls")
```

Integration requirements:

* Uses existing `AUTH_USER_MODEL`
* Respects Django sessions
* Reuses existing database
* Optional Django admin for project/item management

---

## 13. Standalone FastAPI Reference Server

Single service providing:

* SQLite (dev)
* Postgres (prod)
* SQLAlchemy models
* Alembic migrations
* Basic token auth or header-based auth

Directory:

```
server/
  main.py
  models.py
  storage.py
  config.py
```

---

## 14. Scalability Considerations

* Cursor-based pagination only
* Indexes:

  * `(project_id, sort_key)`
  * `(item_id, sort_order, variant_key)`
  * `(project_id, user_id, item_id)`
  * `(project_id, user_id, event_id)`
* Batch ingest (200 events/request)
* CDN for media
* Optional partitioning by project
* Rate limit defaults:
  * `POST /events`: 60 req/min/user
  * `GET` endpoints: 600 req/min/user
* Export defaults:
  * max concurrent export jobs per user: 2
  * max export rows per job: 1,000,000
  * max export file size: 5 GB
  * export artifact TTL after ready: 7 days

---

## 15. UX Requirements

* Full keyboard navigation
* Zero mouse required
* Instant decision feedback
* Visible sync status banner
* Visible offline warning
* Resume where left off
* Fast switching between items
* Decision override allowed
* Conflict-free resume after reconnect using deterministic event ordering
* Variant navigation via keyboard (`up/down`) and mouse wheel
* Two-variant compare mode with draggable reveal divider
* One-step local export of full browser state and restore via import

---

## 16. URL State and Deep Linking

The full view state must be representable in URL query parameters so a copied URL restores the same page state.

Required URL state fields:

* `item`: item ID
* `variant`: active variant key
* `compare`: `0|1`
* `compare_a`: first variant key (required when `compare=1`)
* `compare_b`: second variant key (required when `compare=1`)
* `reveal`: integer `0..100`

Optional URL state fields:

* `zoom`: decimal zoom factor
* `pan_x`: normalized viewport offset
* `pan_y`: normalized viewport offset
* `ui_v`: URL state schema version

Rules:

* URL is canonical source for view state on load and hard refresh
* Relevant view-state changes must update URL using history replace by default
* Item navigation should use history push to preserve back/forward behavior
* Invalid URL params must gracefully fallback to defaults while preserving valid params
* URL bounds:
  * `reveal` integer in `[0,100]` (default `50`)
  * `zoom` decimal in `[0.1,20]` (default `1.0`)
  * `pan_x` decimal in `[-1,1]` (default `0`)
  * `pan_y` decimal in `[-1,1]` (default `0`)
* Out-of-range numeric params must be clamped to bounds; unparsable params must fallback to defaults
* Shared URLs must restore the same item, variants, compare state, and reveal position when accessible
* URL must never include credentials, auth tokens, or signed media URLs
* Authorization checks still apply; inaccessible resources return `404`/`403` per security rules

---

## 17. Non-Goals

* Annotation
* Multi-label classification workflows
* Real-time collaborative editing
* Complex workflow engines
* In-product model training, model serving, or automated decisioning

---

## 18. Open Source Requirements

* MIT or Apache 2.0 license
* No heavy frontend framework required
* Clear API contract
* Modular backend adapters
* Minimal external dependencies

---

## 19. Implementation Phases

### Phase 1

* Image-only
* Decision schema
* IndexedDB + sync
* Local browser export/import of review state
* External ML export jobs (server-side snapshot + download)
* Django adapter
* FastAPI standalone
* API v1 contracts in this document

Phase 1 completion criteria:

* Decision-to-UI latency (local optimistic update): p95 < 50ms on a mid-range laptop
* Sync ack latency for online client: p95 < 2s under normal network conditions
* No decision loss in crash-recovery test (kill tab/process during pending queue flush)
* Local export/import round-trip reproduces equivalent local state without data loss
* External ML export produces reproducible manifest + dataset with deterministic row count/hash for same snapshot/filter
* All API contract tests pass for idempotency, cursor behavior, and role enforcement

### Phase 2

* Video renderer
* PDF support
* Storage plugins
* Multi-variant image support
* Two-variant compare mode with reveal divider
* URL-state deep linking

### Phase 3

* Org-level RBAC
* Admin UI
* Optional plugin system

---

## 20. Data Lifecycle and Deletion

* `project` and `item` support soft delete via `deleted_at`
* Soft-deleted entities are excluded from default list APIs
* `decision_event` is append-only and immutable in normal operation
* Hard deletion of events, if required for compliance, must be an explicit admin-only maintenance operation with audit logging

---

## 21. Observability and Testing

Minimum observability:

* Structured logs with `project_id`, `user_id`, `session_id`, `event_id`, and request ID
* Metrics:
  * event ingest rate
  * duplicate event rate
  * event rejection rate
  * sync queue depth (client-side telemetry where available)
  * p95 sync round-trip latency
  * export job duration
  * export failure rate
  * export bytes produced

Contract test matrix (minimum):

* Duplicate event replay
* Out-of-order event arrival
* Invalid and expired cursors
* Permission failures per role
* Signed URL expiry + refresh flow
* Offline queue replay after reconnect
* Variant navigation via keyboard and wheel
* Compare mode restore from URL (`compare_a`, `compare_b`, `reveal`)
* Full URL state round-trip (copy URL, open new tab/session, same state restored)
* Invalid URL-state params fallback behavior
* Direct deep link loading by `item` URL param when item is outside current page
* Local export/import round-trip with pending unsynced events
* Import conflict handling with already-acked events (no duplication)
* External ML export manifest reproducibility for same snapshot/filter
* Field allowlist enforcement (blocked sensitive fields)
* Export expiry behavior (`410 export_expired`)

---

## 22. Export for External ML

triagedeck provides label/data export for external machine-learning workflows while keeping ML execution outside the product.

Export target use case:

* User manually reviews a subset
* User exports labeled dataset snapshot
* User trains classifier externally
* User applies predictions outside triagedeck

Export dataset contract (minimum columns):

* `item_id`
* `external_id`
* `decision_id`
* `note`
* `ts_server`
* `user_id` (optional depending on policy)
* `variant_key` (nullable)
* Selected allowlisted metadata fields

Manifest contract (required):

* `snapshot_at`
* `project_id`
* `decision_schema_version`
* `label_policy`
* `filters`
* `row_count`
* `sha256`

Data reference policy:

* Default export includes logical URIs (stable references), not ephemeral signed media URLs
* Optional resolved-URL export may be supported with explicit expiry metadata

Governance and safety:

* Metadata export is controlled by allowlist/denylist
* Every export request must be audit-logged
* Export files have configurable TTL and are not permanent by default
* Server may apply row/file-size limits and reject oversized export requests with `422` and `error.code=export_limit_exceeded`

---

## 23. Future Ideas (Non-Urgent, Not Planned Soon)

The following ideas are intentionally separated from the urgent roadmap and are not planned for the foreseeable future.

* Linked multi-panel views (raw media + processed output + plots)
* Time-locked multimodal navigation (video, traces, event markers)
* Optional non-editable ROI/mask/landmark overlays
* Event marker tracks with jump shortcuts
* Decision templates and standardized reason-code libraries
* Per-item QC metrics panel with threshold badges
* Reviewer confidence score per decision
* Multi-pass review assignment and adjudication workflows
* Saved dynamic filtered queues for targeted QC
* Session/context breadcrumbs (subject/session/protocol/pipeline hash)
* Keyboard-first quick measurement tools
* Full provenance export and audit replay of reviewer view state
* Plugin hooks for neuroscience-specific renderers (e.g., NWB)
* Statistical drift monitoring of reviewer behavior/data quality

---

## 24. Deliverables

* `docs/api.md`
* `docs/architecture.md`
* `client/`
* `django_app/`
* `fastapi_server/`
* `example_config.json`
