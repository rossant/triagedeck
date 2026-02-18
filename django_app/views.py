from __future__ import annotations

import base64
import json
import uuid

from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from django_app.models import DecisionEvent, DecisionLatest, Item, ItemVariant, Project
from django_app.permissions import can_write_events, project_role_or_404, require_auth

CURSOR_TTL_MS = 7 * 24 * 60 * 60 * 1000
SKEW_WINDOW_MS = 24 * 60 * 60 * 1000


def now_ms() -> int:
    return int(timezone.now().timestamp() * 1000)


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


def decode_cursor(value: str | None):
    if not value:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(value.encode("utf-8")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_cursor") from exc
    if payload.get("exp", 0) < now_ms():
        raise ValueError("invalid_cursor")
    return payload.get("payload")


def encode_cursor(payload: dict):
    raw = json.dumps({"payload": payload, "exp": now_ms() + CURSOR_TTL_MS}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


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
        limit = min(max(int(request.GET.get("limit", "100")), 1), 200)
    except ValueError:
        return api_error(400, "bad_request", "Invalid limit")

    try:
        cursor = decode_cursor(request.GET.get("cursor"))
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


@require_http_methods(["POST"])
def events_post(request, project_id):
    try:
        ctx = require_auth(request)
        role = project_role_or_404(project_id, ctx.user_id)
    except PermissionError:
        return api_error(401, "unauthorized", "Authentication required")
    except Http404:
        return api_error(404, "not_found", "Resource not found")

    if not can_write_events(role):
        return api_error(403, "forbidden", "You do not have permission for this action")

    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
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

            if not item_id or uuid.UUID(item_id) not in item_ids:
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

            item = Item.objects.get(id=item_id)
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
        limit = min(max(int(request.GET.get("limit", "500")), 1), 2000)
    except ValueError:
        return api_error(400, "bad_request", "Invalid limit")

    try:
        cursor = decode_cursor(request.GET.get("cursor"))
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
