from __future__ import annotations

import base64
import json
import time
import uuid

from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from django_app.export_storage import ExportStorage
from django_app.models import (
    DecisionEvent,
    DecisionLatest,
    ExportJob,
    Item,
    ItemVariant,
    Project,
    Role,
)
from django_app.observability import increment, log_event, observe_ms, snapshot
from django_app.permissions import can_write_events, project_role_or_404, require_auth

CURSOR_TTL_MS = 7 * 24 * 60 * 60 * 1000
SKEW_WINDOW_MS = 24 * 60 * 60 * 1000
EXPORT_TTL_MS = 7 * 24 * 60 * 60 * 1000
EXPORT_MAX_ROWS = 1_000_000
EXPORT_MAX_BYTES = 5 * 1024 * 1024 * 1024
EXPORT_MAX_CONCURRENT_PER_USER = 2
DEFAULT_EXPORT_ALLOWLIST = {
    "item_id",
    "external_id",
    "decision_id",
    "note",
    "ts_server",
    "variant_key",
    "metadata.subject_id",
    "metadata.session_id",
}
DEFAULT_EXPORT_FIELDS = ["item_id", "external_id", "decision_id", "note", "ts_server"]
export_store = ExportStorage()


def now_ms() -> int:
    return int(timezone.now().timestamp() * 1000)


@require_http_methods(["GET"])
def metrics_view(request):
    return JsonResponse(snapshot())


def api_error(status: int, code: str, message: str, details: dict | None = None):
    return JsonResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
        status=status,
    )


def decode_cursor(value: str | None, required_keys: tuple[str, ...]):
    if not value:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(value.encode("utf-8")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_cursor") from exc
    exp = payload.get("exp")
    cursor_payload = payload.get("payload")
    if not isinstance(exp, int):
        raise ValueError("invalid_cursor")
    if exp < now_ms():
        raise ValueError("invalid_cursor")
    if not isinstance(cursor_payload, dict):
        raise ValueError("invalid_cursor")
    if any(k not in cursor_payload for k in required_keys):
        raise ValueError("invalid_cursor")
    return cursor_payload


def encode_cursor(payload: dict):
    raw = json.dumps({"payload": payload, "exp": now_ms() + CURSOR_TTL_MS}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def parse_limit(raw_value: str | None, *, default: int, min_value: int, max_value: int) -> int:
    if raw_value is None:
        return default
    try:
        raw = int(raw_value)
    except ValueError as exc:
        raise ValueError("bad_request") from exc
    return min(max(raw, min_value), max_value)


def item_to_json(row: Item):
    variants = [
        {
            "variant_key": v.variant_key,
            "label": v.label,
            "uri": v.uri,
            "sort_order": v.sort_order,
            "metadata": v.metadata_json,
        }
        for v in ItemVariant.objects.filter(item=row).order_by("sort_order", "variant_key")
    ]
    return {
        "item_id": str(row.id),
        "external_id": row.external_id,
        "media_type": row.media_type,
        "uri": row.uri,
        "variants": variants,
        "metadata": row.metadata_json,
    }


@require_http_methods(["GET"])
def projects_list(request):
    try:
        ctx = require_auth(request)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")

    rows = (
        Project.objects.filter(projectmembership__user_id=ctx.user_id, deleted_at__isnull=True)
        .order_by("name")
        .values("id", "name", "slug")
    )
    return JsonResponse(
        {
            "projects": [
                {
                    "project_id": str(r["id"]),
                    "name": r["name"],
                    "slug": r["slug"],
                }
                for r in rows
            ]
        }
    )


@require_http_methods(["GET"])
def project_config(request, project_id):
    try:
        ctx = require_auth(request)
        project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    row = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if row is None:
        return api_error(404, "not_found", "Resource not found")

    cfg = row.config_json or {}
    return JsonResponse(
        {
            "project": {
                "project_id": str(row.id),
                "name": row.name,
                "slug": row.slug,
            },
            "decision_schema": row.decision_schema_json,
            "media_types_supported": cfg.get("media_types_supported", ["image"]),
            "variants_enabled": cfg.get("variants_enabled", False),
            "variant_navigation_mode": cfg.get("variant_navigation_mode", "horizontal"),
            "compare_mode_enabled": cfg.get("compare_mode_enabled", False),
            "max_compare_variants": cfg.get("max_compare_variants", 2),
        }
    )


@require_http_methods(["GET"])
def items_list(request, project_id):
    try:
        ctx = require_auth(request)
        project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    try:
        limit = parse_limit(request.GET.get("limit"), default=100, min_value=1, max_value=200)
    except ValueError:
        return api_error(400, "bad_request", "Invalid limit")

    try:
        cursor = decode_cursor(request.GET.get("cursor"), ("sort_key", "item_id"))
    except ValueError:
        return api_error(400, "invalid_cursor", "Cursor is invalid or expired")

    qs = Item.objects.filter(project_id=project_id, deleted_at__isnull=True)
    if cursor:
        qs = qs.filter(
            Q(sort_key__gt=cursor["sort_key"])
            | Q(sort_key=cursor["sort_key"], id__gt=cursor["item_id"])
        )
    rows = list(qs.order_by("sort_key", "id")[:limit])

    next_cursor = None
    if rows:
        last = rows[-1]
        next_cursor = encode_cursor({"sort_key": last.sort_key, "item_id": str(last.id)})

    return JsonResponse({"items": [item_to_json(r) for r in rows], "next_cursor": next_cursor})


@require_http_methods(["GET"])
def item_get(request, project_id, item_id):
    try:
        ctx = require_auth(request)
        project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    row = Item.objects.filter(id=item_id, project_id=project_id, deleted_at__isnull=True).first()
    if row is None:
        return api_error(404, "not_found", "Resource not found")
    return JsonResponse(item_to_json(row))


@require_http_methods(["GET"])
def item_url(request, project_id, item_id):
    try:
        ctx = require_auth(request)
        project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    row = Item.objects.filter(id=item_id, project_id=project_id, deleted_at__isnull=True).first()
    if row is None:
        return api_error(404, "not_found", "Resource not found")

    variant_key = request.GET.get("variant_key")
    uri = row.uri
    if variant_key:
        variant = ItemVariant.objects.filter(item=row, variant_key=variant_key).first()
        if not variant:
            return api_error(404, "not_found", "Resource not found")
        uri = variant.uri

    return JsonResponse(
        {
            "item_id": str(row.id),
            "uri": uri,
            "expires_at": now_ms() + (15 * 60 * 1000),
        }
    )


def _event_rank(ts_client_effective: int, ts_server: int, event_id: str):
    return (ts_client_effective, ts_server, event_id)


def _parse_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return None


def _cleanup_expired_exports(project_id) -> None:
    now = now_ms()
    rows = list(
        ExportJob.objects.filter(
            project_id=project_id,
            expires_at__lt=now,
        )
        .exclude(status=ExportJob.STATUS_EXPIRED)
        .only("id", "file_uri")
    )
    for row in rows:
        if row.file_uri:
            export_store.remove_artifacts_for_uri(row.file_uri)
        ExportJob.objects.filter(id=row.id).update(
            status=ExportJob.STATUS_EXPIRED,
            completed_at=now,
        )
        export_store.audit("export_expired_cleanup", {"export_id": str(row.id)})


def _normalize_include_fields(include_fields: list[str]) -> list[str]:
    return include_fields or DEFAULT_EXPORT_FIELDS


def _extract_export_value(field: str, row: DecisionLatest):
    if field == "item_id":
        return str(row.item_id)
    if field == "external_id":
        return row.item.external_id
    if field == "decision_id":
        return row.decision_id
    if field == "note":
        return row.note
    if field == "ts_server":
        return row.ts_server
    if field == "variant_key":
        return None
    if field.startswith("metadata."):
        key = field.split(".", 1)[1]
        return (row.item.metadata_json or {}).get(key)
    return None


@require_http_methods(["POST"])
def events_post(request, project_id):
    t0 = time.perf_counter()
    try:
        ctx = require_auth(request)
        role = project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    if not can_write_events(role):
        return api_error(403, "forbidden", "You do not have permission for this action")

    body = _parse_json_body(request)
    if body is None:
        return api_error(400, "bad_request", "Invalid JSON body")

    events = body.get("events") or []
    if len(events) > 200:
        return api_error(422, "too_many_events", "Maximum 200 events per request")

    project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if project is None:
        return api_error(404, "not_found", "Resource not found")

    schema = project.decision_schema_json or {}
    allow_notes = bool(schema.get("allow_notes", False))
    allowed_ids = {c.get("id") for c in schema.get("choices", [])}

    accepted = 0
    duplicate = 0
    rejected = 0
    results = []
    server_ts = now_ms()

    with transaction.atomic():
        item_ids = set(
            Item.objects.filter(project_id=project_id, deleted_at__isnull=True).values_list(
                "id",
                flat=True,
            )
        )

        for ev in events:
            event_id = ev.get("event_id")
            item_id = ev.get("item_id")
            decision_id = ev.get("decision_id")
            note = (ev.get("note") or "")[:2000]
            ts_client = int(ev.get("ts_client") or 0)

            if DecisionEvent.objects.filter(
                project_id=project_id,
                user_id=ctx.user_id,
                event_id=event_id,
            ).exists():
                duplicate += 1
                results.append({"event_id": event_id, "status": "duplicate"})
                continue

            try:
                parsed_item_id = uuid.UUID(item_id) if item_id else None
            except (ValueError, TypeError):
                parsed_item_id = None

            if parsed_item_id not in item_ids:
                rejected += 1
                results.append(
                    {
                        "event_id": event_id,
                        "status": "rejected",
                        "error_code": "item_not_in_project",
                    }
                )
                continue

            if decision_id not in allowed_ids:
                rejected += 1
                results.append(
                    {
                        "event_id": event_id,
                        "status": "rejected",
                        "error_code": "invalid_decision_id",
                    }
                )
                continue

            if (not allow_notes) and note.strip():
                rejected += 1
                results.append(
                    {
                        "event_id": event_id,
                        "status": "rejected",
                        "error_code": "notes_disabled",
                    }
                )
                continue

            low = server_ts - SKEW_WINDOW_MS
            high = server_ts + SKEW_WINDOW_MS
            ts_client_effective = max(low, min(high, ts_client))

            item = Item.objects.get(id=parsed_item_id)
            DecisionEvent.objects.create(
                project_id=project_id,
                user_id=ctx.user_id,
                event_id=event_id,
                item=item,
                decision_id=decision_id,
                note=note,
                ts_client=ts_client,
                ts_client_effective=ts_client_effective,
                ts_server=server_ts,
            )

            latest = DecisionLatest.objects.filter(
                project_id=project_id,
                user_id=ctx.user_id,
                item_id=item_id,
            ).first()
            if not latest or _event_rank(ts_client_effective, server_ts, event_id) > _event_rank(
                latest.ts_client_effective,
                latest.ts_server,
                str(latest.event_id),
            ):
                DecisionLatest.objects.update_or_create(
                    project_id=project_id,
                    user_id=ctx.user_id,
                    item_id=item_id,
                    defaults={
                        "event_id": event_id,
                        "decision_id": decision_id,
                        "note": note,
                        "ts_client": ts_client,
                        "ts_client_effective": ts_client_effective,
                        "ts_server": server_ts,
                    },
                )

            accepted += 1
            results.append({"event_id": event_id, "status": "accepted"})

    increment("events.ingest.calls")
    increment("events.ingest.accepted", accepted)
    increment("events.ingest.duplicate", duplicate)
    increment("events.ingest.rejected", rejected)
    observe_ms("events.ingest.latency_ms", (time.perf_counter() - t0) * 1000.0)
    log_event(
        "events.ingest",
        project_id=str(project_id),
        user_id=ctx.user_id,
        accepted=accepted,
        duplicate=duplicate,
        rejected=rejected,
    )
    return JsonResponse(
        {
            "acked": accepted + duplicate,
            "accepted": accepted,
            "duplicate": duplicate,
            "rejected": rejected,
            "server_ts": server_ts,
            "results": results,
        }
    )


def _export_visible_queryset(project_id, user_id: int, role: str):
    qs = ExportJob.objects.filter(project_id=project_id)
    if role != Role.ADMIN:
        qs = qs.filter(requested_by_user_id=user_id)
    return qs


@require_http_methods(["POST"])
def exports_create(request, project_id):
    t0 = time.perf_counter()
    try:
        ctx = require_auth(request)
        role = project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    if role not in {Role.ADMIN, Role.REVIEWER}:
        return api_error(403, "forbidden", "You do not have permission for this action")

    body = _parse_json_body(request)
    if body is None:
        return api_error(400, "bad_request", "Invalid JSON body")
    _cleanup_expired_exports(project_id)

    project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not project:
        return api_error(404, "not_found", "Resource not found")

    include_fields = _normalize_include_fields(body.get("include_fields") or [])
    running_count = ExportJob.objects.filter(
        project_id=project_id,
        requested_by_user_id=ctx.user_id,
        status__in=[ExportJob.STATUS_QUEUED, ExportJob.STATUS_RUNNING],
    ).count()
    if running_count >= EXPORT_MAX_CONCURRENT_PER_USER:
        return api_error(422, "export_limit_exceeded", "Too many concurrent export jobs")

    allowlist = set((project.config_json or {}).get("export_allowlist", []))
    if not allowlist:
        allowlist = DEFAULT_EXPORT_ALLOWLIST
    for field in include_fields:
        if field not in allowlist:
            return api_error(422, "field_not_allowlisted", f"Field not allowlisted: {field}")

    created_at = now_ms()
    rows = list(
        DecisionLatest.objects.filter(project_id=project_id)
        .select_related("item")
        .order_by("ts_server", "item_id")
    )
    row_count = len(rows)
    if row_count > EXPORT_MAX_ROWS:
        return api_error(422, "export_limit_exceeded", "Export exceeds max rows")

    export_rows = [
        {field: _extract_export_value(field, row) for field in include_fields} for row in rows
    ]
    manifest = {
        "snapshot_at": created_at,
        "project_id": str(project_id),
        "decision_schema_version": (project.decision_schema_json or {}).get("version", 1),
        "label_policy": body.get("label_policy", "latest_per_user"),
        "filters": body.get("filters", {}),
        "include_fields": include_fields,
        "row_count": row_count,
        "sha256": "",
    }

    artifact = export_store.write_bundle(
        project_id=str(project_id),
        snapshot_at=created_at,
        fmt=body.get("format", "jsonl"),
        include_fields=include_fields,
        rows=export_rows,
        manifest=manifest,
    )
    if artifact.size_bytes > EXPORT_MAX_BYTES:
        export_store.remove_artifacts_for_uri(artifact.file_uri)
        return api_error(422, "export_limit_exceeded", "Export exceeds max file size")
    manifest["sha256"] = artifact.sha256

    job = ExportJob.objects.create(
        project_id=project_id,
        requested_by_user_id=ctx.user_id,
        status=ExportJob.STATUS_READY,
        mode=body.get("mode", ExportJob.MODE_LABELS_ONLY),
        label_policy=body.get("label_policy", "latest_per_user"),
        format=body.get("format", "jsonl"),
        filters_json=body.get("filters", {}),
        include_fields_json=include_fields,
        manifest_json=manifest,
        file_uri=artifact.file_uri,
        expires_at=created_at + EXPORT_TTL_MS,
        created_at=created_at,
        completed_at=created_at,
    )
    export_store.audit(
        "export_ready",
        {
            "export_id": str(job.id),
            "project_id": str(project_id),
            "row_count": artifact.row_count,
            "sha256": artifact.sha256,
        },
    )
    increment("exports.create.calls")
    increment("exports.create.ready", 1)
    observe_ms("exports.create.latency_ms", (time.perf_counter() - t0) * 1000.0)
    log_event(
        "exports.create",
        project_id=str(project_id),
        user_id=ctx.user_id,
        export_id=str(job.id),
        row_count=artifact.row_count,
    )
    return JsonResponse({"export_id": str(job.id), "status": "queued"})


@require_http_methods(["GET"])
def exports_list(request, project_id):
    t0 = time.perf_counter()
    try:
        ctx = require_auth(request)
        role = project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    _cleanup_expired_exports(project_id)
    try:
        limit = parse_limit(request.GET.get("limit"), default=50, min_value=1, max_value=100)
    except ValueError:
        return api_error(400, "bad_request", "Invalid limit")

    try:
        cursor = decode_cursor(request.GET.get("cursor"), ("created_at", "id"))
    except ValueError:
        return api_error(400, "invalid_cursor", "Cursor is invalid or expired")

    qs = _export_visible_queryset(project_id, ctx.user_id, role)
    if cursor:
        qs = qs.filter(
            Q(created_at__lt=cursor["created_at"])
            | Q(created_at=cursor["created_at"], id__lt=cursor["id"])
        )
    rows = list(qs.order_by("-created_at", "-id")[:limit])
    next_cursor = None
    if rows:
        last = rows[-1]
        next_cursor = encode_cursor({"created_at": last.created_at, "id": str(last.id)})

    increment("exports.list.calls")
    observe_ms("exports.list.latency_ms", (time.perf_counter() - t0) * 1000.0)
    return JsonResponse(
        {
            "exports": [
                {
                    "export_id": str(r.id),
                    "status": r.status,
                    "format": r.format,
                    "mode": r.mode,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
            "next_cursor": next_cursor,
        }
    )


@require_http_methods(["GET"])
def exports_get(request, project_id, export_id):
    t0 = time.perf_counter()
    try:
        ctx = require_auth(request)
        role = project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    _cleanup_expired_exports(project_id)
    row = ExportJob.objects.filter(id=export_id, project_id=project_id).first()
    if not row:
        return api_error(404, "not_found", "Resource not found")
    if role != Role.ADMIN and row.requested_by_user_id != ctx.user_id:
        return api_error(403, "forbidden", "You do not have permission for this action")
    if row.expires_at and row.expires_at < now_ms():
        return api_error(410, "export_expired", "Export has expired")

    out = JsonResponse(
        {
            "export_id": str(row.id),
            "status": row.status,
            "format": row.format,
            "mode": row.mode,
            "manifest": row.manifest_json,
            "download_url": row.file_uri,
            "expires_at": row.expires_at,
        }
    )
    increment("exports.get.calls")
    observe_ms("exports.get.latency_ms", (time.perf_counter() - t0) * 1000.0)
    return out


@require_http_methods(["DELETE"])
def exports_cancel(request, project_id, export_id):
    t0 = time.perf_counter()
    try:
        ctx = require_auth(request)
        role = project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    _cleanup_expired_exports(project_id)
    row = ExportJob.objects.filter(id=export_id, project_id=project_id).first()
    if not row:
        return api_error(404, "not_found", "Resource not found")
    if role != Role.ADMIN and row.requested_by_user_id != ctx.user_id:
        return api_error(403, "forbidden", "You do not have permission for this action")

    if row.status == ExportJob.STATUS_READY:
        return api_error(409, "export_ready", "Cannot cancel a ready export")
    if row.status in {ExportJob.STATUS_FAILED, ExportJob.STATUS_EXPIRED}:
        return JsonResponse({"status": row.status})

    if row.file_uri:
        export_store.remove_artifacts_for_uri(row.file_uri)
    row.status = ExportJob.STATUS_FAILED
    row.error_code = "export_cancelled"
    row.completed_at = now_ms()
    row.save(update_fields=["status", "error_code", "completed_at"])
    export_store.audit(
        "export_cancelled",
        {"export_id": str(row.id), "project_id": str(project_id)},
    )
    increment("exports.cancel.calls")
    observe_ms("exports.cancel.latency_ms", (time.perf_counter() - t0) * 1000.0)
    return JsonResponse({"status": "failed", "error": {"code": "export_cancelled"}})


@require_http_methods(["GET", "POST"])
def exports_collection(request, project_id):
    if request.method == "GET":
        return exports_list(request, project_id)
    return exports_create(request, project_id)


@require_http_methods(["GET", "DELETE"])
def exports_detail(request, project_id, export_id):
    if request.method == "GET":
        return exports_get(request, project_id, export_id)
    return exports_cancel(request, project_id, export_id)


@require_http_methods(["GET"])
def decisions_list(request, project_id):
    try:
        ctx = require_auth(request)
        project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    try:
        limit = parse_limit(request.GET.get("limit"), default=500, min_value=1, max_value=2000)
    except ValueError:
        return api_error(400, "bad_request", "Invalid limit")

    try:
        cursor = decode_cursor(request.GET.get("cursor"), ("ts_server", "item_id"))
    except ValueError:
        return api_error(400, "invalid_cursor", "Cursor is invalid or expired")

    qs = DecisionLatest.objects.filter(project_id=project_id, user_id=ctx.user_id)
    if cursor:
        qs = qs.filter(
            Q(ts_server__gt=cursor["ts_server"])
            | Q(ts_server=cursor["ts_server"], item_id__gt=cursor["item_id"])
        )

    rows = list(qs.order_by("ts_server", "item_id")[:limit])
    next_cursor = None
    if rows:
        last = rows[-1]
        next_cursor = encode_cursor({"ts_server": last.ts_server, "item_id": str(last.item_id)})

    return JsonResponse(
        {
            "decisions": [
                {
                    "item_id": str(r.item_id),
                    "decision_id": r.decision_id,
                    "note": r.note,
                    "ts_client": r.ts_client,
                    "ts_server": r.ts_server,
                    "event_id": str(r.event_id),
                }
                for r in rows
            ],
            "next_cursor": next_cursor,
        }
    )
