# triagedeck API Contract (v1)

Base path: `/api/v1`

All endpoints are authenticated and project-scoped.

## Common Conventions

- Time fields are Unix epoch milliseconds.
- UUID fields are RFC 4122 strings.
- Cursor values are opaque.
- Response `Content-Type` is `application/json` unless noted.

### Error Shape

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable message",
    "details": {}
  }
}
```

### Standard HTTP Errors

- `400 bad_request`
- `401 unauthorized`
- `403 forbidden`
- `404 not_found`
- `409 conflict`
- `410 gone`
- `422 validation_error`
- `429 rate_limited`
- `500 internal_error`

## Auth and Roles

- `admin`: full read/write in org projects.
- `reviewer`: read projects/items/config, write events, create external-ML exports.
- `viewer`: read-only; export creation only if explicitly enabled by org policy.

Non-membership returns `404`.

## Endpoints

## `GET /projects`

Returns projects visible to current user.

## `GET /projects/{project_id}/config`

Returns project config and capabilities.

```json
{
  "project": {},
  "decision_schema": {},
  "media_types_supported": ["image", "video", "pdf"],
  "variants_enabled": true,
  "variant_navigation_mode": "both",
  "compare_mode_enabled": true,
  "max_compare_variants": 2
}
```

Rules:

- `variant_navigation_mode`: `horizontal | vertical | both`
- `max_compare_variants` is `2`.

## `GET /projects/{project_id}/items?cursor=<opaque>&limit=200`

Lists items with optional variants.

```json
{
  "items": [
    {
      "item_id": "uuid",
      "external_id": "img_0001",
      "media_type": "image",
      "uri": "logical-or-resolved-uri",
      "variants": [
        {
          "variant_key": "before",
          "label": "Before",
          "uri": "logical-or-resolved-uri",
          "sort_order": 10,
          "metadata": {}
        }
      ],
      "metadata": {}
    }
  ],
  "next_cursor": "opaque-or-null"
}
```

Rules:

- Ordered by `(sort_key ASC, item_id ASC)`.
- `limit` default `100`, max `200`.
- Cursor expires after `7 days`.
- Invalid/expired cursor => `400` + `error.code=invalid_cursor`.
- Excludes soft-deleted items.
- `variants` ordered by `(sort_order ASC, variant_key ASC)`.

## `GET /projects/{project_id}/items/{item_id}`

Gets a single item (deep-link hydration).

Rules:

- Returns `404` if missing, soft-deleted, or inaccessible.
- Variant ordering/optionality matches list endpoint.

## `GET /projects/{project_id}/items/{item_id}/url[?variant_key=<key>]`

Refreshes signed URL for an item or specific variant.

```json
{
  "item_id": "uuid",
  "uri": "https://signed-url",
  "expires_at": 1739472600000
}
```

Rules:

- `variant_key` optional; if provided, must exist for `item_id`.

## `POST /projects/{project_id}/events`

Ingests decision events (batch, idempotent).

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

Rules:

- Max `200` events/request.
- Per-event processing (partial success allowed).
- `acked = accepted + duplicate`.
- Duplicate key: `(project_id, user_id, event_id)`.
- `decision_id` must exist in active schema version.
- `note` max length `2000`; reject non-empty note if `allow_notes=false`.
- Persist `ts_server` and `ts_client_effective`.

## `GET /projects/{project_id}/decisions?cursor=<opaque>&limit=500`

Fetches latest decision state for current user.

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

- Returns from `decision_latest` for `request.user.id` only.
- Ordered by `(ts_server ASC, item_id ASC)`.
- `limit` default `500`, max `2000`.
- Cursor expires after `7 days`.

## External ML Export APIs

## `POST /projects/{project_id}/exports`

Creates export job.

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
    "metadata": {"session_id": ["session-01"]}
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

```json
{
  "export_id": "uuid",
  "status": "queued"
}
```

Rules:

- Supported `label_policy`: `latest_per_user`.
- Default `format`: `jsonl`.
- Snapshot taken at job start (`snapshot_at` in manifest).
- `include_fields` validated against allowlist:
  - `project.config_json.export_allowlist`, fallback to server global allowlist.
- Non-allowlisted fields => `422` + `error.code=field_not_allowlisted`.
- Default creation role: `reviewer`/`admin`.

## `GET /projects/{project_id}/exports/{export_id}`

Gets export status and download location.

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

- Download access default: export creator + admins.
- Optional policy may allow reviewer access to others' exports in project.
- Expired job => `410` + `error.code=export_expired`.

## `GET /projects/{project_id}/exports?cursor=<opaque>&limit=100`

Lists exports.

Rules:

- Ordered by `(created_at DESC, id DESC)`.
- `limit` default `50`, max `100`.

## `DELETE /projects/{project_id}/exports/{export_id}`

Cancels queued/running export.

Rules:

- Idempotent.
- Allowed states: `queued`, `running`.
- Cancel transitions to `failed` + `error.code=export_cancelled`.
- If already `ready`, return `409`.

## Export Artifact Contract

Default package filename:

- `triagedeck_export_{project_id}_{snapshot_at}.{ext}`

Package contents:

- dataset file (`.jsonl`, `.csv`, or `.parquet`)
- `manifest.json`

Manifest required fields:

- `snapshot_at`
- `project_id`
- `decision_schema_version`
- `label_policy`
- `filters`
- `row_count`
- `sha256`

Policy:

- Default export media references are logical URIs (not ephemeral signed URLs).
- Export must not include tokens, cookies, or credentials.
- Export limits: max concurrent jobs/user `2`, max rows `1,000,000`, max size `5 GB`, artifact TTL `7 days`.
