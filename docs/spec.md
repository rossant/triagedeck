# triagedeck: Generic Media Review System (Open Source)

**Specification v1.0**

---

## 1. Purpose

A lightweight, open-source, keyboard-driven media review system designed for:

* High-throughput **image review (priority use case)**
* Optional **video and PDF support**
* Customizable decision sets (not limited to PASS/FAIL)
* Strong offline robustness and data integrity
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
Storage Resolver Layer
    ↓
Database + Object Storage
```

### Layers

| Layer            | Responsibility                                  |
| ---------------- | ----------------------------------------------- |
| Client           | Rendering, navigation, decisions, offline queue |
| API              | Authentication, authorization, data validation  |
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
```

Important:

* `external_id` must be stable
* `sort_key` indexed for fast cursor pagination

---

### 5.6 Decision Event (append-only)

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
  ts_server
```

Unique constraint:

```
(project_id, user_id, event_id)
```

---

### 5.7 Latest Decision (materialized state)

```
decision_latest
  project_id
  user_id
  item_id
  decision_id
  note
  ts_client
  ts_server
```

Unique constraint:

```
(project_id, user_id, item_id)
```

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

---

## 7. API Specification

All endpoints are authenticated.

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
  "media_types_supported": ["image", "video", "pdf"]
}
```

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
      "metadata": {...}
    }
  ],
  "next_cursor": "opaque-or-null"
}
```

Must use indexed cursor (not offset).

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
  "server_ts": 1739472100000
}
```

Must be idempotent.

---

### 7.5 Fetch Decisions (Resume)

```
GET /api/projects/{project_id}/decisions?cursor=<opaque>
```

---

## 8. Client Architecture

### 8.1 Core Components

* `App`
* `Router`
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

---

## 9. Media Rendering

### 9.1 Renderer Interface

```js
class Renderer {
  mount(container, item)
  unmount()
  onKey(event)
  prefetch(item)
}
```

---

### 9.2 Image Renderer

* Single `<img>` or `<canvas>`
* Prefetch next N
* LRU memory cap
* No thousands of DOM nodes

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

---

## 11. Security Model

* All API routes authenticated
* All routes scoped by project
* Validate item belongs to project
* Use signed URLs for private storage
* Optional reverse-proxy auth integration
* CSRF protection if using cookies

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
  * `(project_id, user_id, item_id)`
  * `(project_id, user_id, event_id)`
* Batch ingest (200 events/request)
* CDN for media
* Optional partitioning by project

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

---

## 16. Non-Goals

* Annotation
* Multi-label classification workflows
* Real-time collaborative editing
* Complex workflow engines

---

## 17. Open Source Requirements

* MIT or Apache 2.0 license
* No heavy frontend framework required
* Clear API contract
* Modular backend adapters
* Minimal external dependencies

---

## 18. Implementation Phases

### Phase 1

* Image-only
* Decision schema
* IndexedDB + sync
* Django adapter
* FastAPI standalone

### Phase 2

* Video renderer
* PDF support
* Storage plugins

### Phase 3

* Org-level RBAC
* Admin UI
* Optional plugin system

---

## 19. Deliverables

* `docs/api.md`
* `docs/architecture.md`
* `client/`
* `django_app/`
* `fastapi_server/`
* `example_config.json`


