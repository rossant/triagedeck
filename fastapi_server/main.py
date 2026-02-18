from __future__ import annotations

import csv
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select

from fastapi_server.auth import User, get_user, project_role_or_404
from fastapi_server.config import settings
from fastapi_server.cursor import decode_cursor, encode_cursor
from fastapi_server.db import (
    decision_event,
    decision_latest,
    export_job,
    item,
    item_variant,
    now_ms,
    project,
    project_membership,
    session_scope,
)
from fastapi_server.errors import (
    bad_request,
    conflict,
    forbidden,
    gone,
    not_found,
    validation_error,
)
from fastapi_server.schemas import EventsIngestRequest, ExportCreateRequest
from fastapi_server.storage import StorageResolver

app = FastAPI(title="triagedeck")
resolver = StorageResolver()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "ts": now_ms()}


@app.get(f"{settings.api_prefix}/projects")
def list_projects(user: User = Depends(get_user)):
    with session_scope() as session:
        rows = session.execute(
            select(project.c.id, project.c.name, project.c.slug)
            .join(project_membership, project_membership.c.project_id == project.c.id)
            .where(
                project.c.deleted_at.is_(None),
                project_membership.c.user_id == user.user_id,
            )
            .order_by(project.c.name.asc())
        ).all()
        return {"projects": [{"project_id": r.id, "name": r.name, "slug": r.slug} for r in rows]}


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/config")
def get_project_config(project_id: str, user: User = Depends(get_user)):
    with session_scope() as session:
        project_role_or_404(session, project_id, user.user_id)
        row = (
            session.execute(
                select(project).where(project.c.id == project_id, project.c.deleted_at.is_(None))
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise not_found()
        cfg = row["config_json"]
        return {
            "project": {"project_id": row["id"], "name": row["name"], "slug": row["slug"]},
            "decision_schema": row["decision_schema_json"],
            "media_types_supported": cfg.get("media_types_supported", ["image"]),
            "variants_enabled": cfg.get("variants_enabled", False),
            "variant_navigation_mode": cfg.get("variant_navigation_mode", "horizontal"),
            "compare_mode_enabled": cfg.get("compare_mode_enabled", False),
            "max_compare_variants": cfg.get("max_compare_variants", 2),
        }


def _check_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        data = decode_cursor(cursor)
    except Exception as exc:
        raise bad_request("invalid_cursor", "Cursor is invalid or expired") from exc
    if data.get("exp", 0) < now_ms():
        raise bad_request("invalid_cursor", "Cursor is invalid or expired")
    return data["payload"]


def _item_variants(session, item_ids: list[str]) -> dict[str, list[dict]]:
    if not item_ids:
        return {}
    rows = session.execute(
        select(item_variant)
        .where(item_variant.c.item_id.in_(item_ids))
        .order_by(
            item_variant.c.item_id.asc(),
            item_variant.c.sort_order.asc(),
            item_variant.c.variant_key.asc(),
        )
    ).mappings()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["item_id"], []).append(
            {
                "variant_key": r["variant_key"],
                "label": r["label"],
                "uri": resolver.resolve(r["uri"], settings.signed_url_ttl_s).uri,
                "sort_order": r["sort_order"],
                "metadata": r["metadata_json"],
            }
        )
    return out


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/items")
def list_items(
    project_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    user: User = Depends(get_user),
):
    payload = _check_cursor(cursor)
    with session_scope() as session:
        project_role_or_404(session, project_id, user.user_id)
        q = select(item).where(
            item.c.project_id == project_id,
            item.c.deleted_at.is_(None),
        )
        if payload:
            q = q.where(
                or_(
                    item.c.sort_key > payload["sort_key"],
                    and_(item.c.sort_key == payload["sort_key"], item.c.id > payload["item_id"]),
                )
            )
        rows = (
            session.execute(q.order_by(item.c.sort_key.asc(), item.c.id.asc()).limit(limit))
            .mappings()
            .all()
        )
        item_ids = [r["id"] for r in rows]
        variants = _item_variants(session, item_ids)
        response_items = [
            {
                "item_id": r["id"],
                "external_id": r["external_id"],
                "media_type": r["media_type"],
                "uri": resolver.resolve(r["uri"], settings.signed_url_ttl_s).uri,
                "variants": variants.get(r["id"], []),
                "metadata": r["metadata_json"],
            }
            for r in rows
        ]
        next_cursor = None
        if rows:
            last = rows[-1]
            next_cursor = encode_cursor(
                {"sort_key": last["sort_key"], "item_id": last["id"]}, settings.cursor_ttl_ms
            )
        return {"items": response_items, "next_cursor": next_cursor}


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/items/{{item_id}}")
def get_item(project_id: str, item_id: str, user: User = Depends(get_user)):
    with session_scope() as session:
        project_role_or_404(session, project_id, user.user_id)
        row = (
            session.execute(
                select(item).where(
                    item.c.id == item_id,
                    item.c.project_id == project_id,
                    item.c.deleted_at.is_(None),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise not_found()
        variants = _item_variants(session, [item_id]).get(item_id, [])
        return {
            "item_id": row["id"],
            "external_id": row["external_id"],
            "media_type": row["media_type"],
            "uri": resolver.resolve(row["uri"], settings.signed_url_ttl_s).uri,
            "variants": variants,
            "metadata": row["metadata_json"],
        }


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/items/{{item_id}}/url")
def refresh_url(
    project_id: str,
    item_id: str,
    variant_key: str | None = Query(default=None),
    user: User = Depends(get_user),
):
    with session_scope() as session:
        project_role_or_404(session, project_id, user.user_id)
        irow = session.execute(
            select(item.c.id, item.c.uri).where(
                item.c.id == item_id, item.c.project_id == project_id, item.c.deleted_at.is_(None)
            )
        ).one_or_none()
        if irow is None:
            raise not_found()
        logical_uri = irow.uri
        if variant_key:
            vrow = session.execute(
                select(item_variant.c.uri).where(
                    item_variant.c.item_id == item_id,
                    item_variant.c.variant_key == variant_key,
                )
            ).one_or_none()
            if not vrow:
                raise not_found()
            logical_uri = vrow.uri
        resolved = resolver.resolve(logical_uri, settings.signed_url_ttl_s)
        return {"item_id": item_id, "uri": resolved.uri, "expires_at": resolved.expires_at}


def _decision_choice_set(decision_schema: dict) -> set[str]:
    return {c.get("id", "") for c in decision_schema.get("choices", [])}


def _rank_key(e: dict) -> tuple[int, int, str]:
    return (e["ts_client_effective"], e["ts_server"], e["event_id"])


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/events")
def ingest_events(project_id: str, payload: EventsIngestRequest, user: User = Depends(get_user)):
    if len(payload.events) > 200:
        raise validation_error("too_many_events", "Maximum 200 events per request")

    with session_scope() as session:
        role = project_role_or_404(session, project_id, user.user_id)
        if role not in {"admin", "reviewer"}:
            raise forbidden()

        prow = session.execute(
            select(project.c.decision_schema_json, project.c.id).where(
                project.c.id == project_id,
                project.c.deleted_at.is_(None),
            )
        ).one_or_none()
        if not prow:
            raise not_found()
        allowed_decisions = _decision_choice_set(prow.decision_schema_json)
        allow_notes = bool(prow.decision_schema_json.get("allow_notes", False))

        item_set = {
            r[0]
            for r in session.execute(
                select(item.c.id).where(
                    item.c.project_id == project_id, item.c.deleted_at.is_(None)
                )
            ).all()
        }

        accepted = 0
        duplicate = 0
        rejected = 0
        results: list[dict] = []
        current_server_ts = now_ms()

        for ev in payload.events:
            existing = session.execute(
                select(decision_event.c.id).where(
                    decision_event.c.project_id == project_id,
                    decision_event.c.user_id == user.user_id,
                    decision_event.c.event_id == ev.event_id,
                )
            ).one_or_none()
            if existing:
                duplicate += 1
                results.append({"event_id": ev.event_id, "status": "duplicate"})
                continue

            if ev.item_id not in item_set:
                rejected += 1
                results.append(
                    {
                        "event_id": ev.event_id,
                        "status": "rejected",
                        "error_code": "item_not_in_project",
                    }
                )
                continue

            if ev.decision_id not in allowed_decisions:
                rejected += 1
                results.append(
                    {
                        "event_id": ev.event_id,
                        "status": "rejected",
                        "error_code": "invalid_decision_id",
                    }
                )
                continue

            if len(ev.note) > 2000:
                rejected += 1
                results.append(
                    {"event_id": ev.event_id, "status": "rejected", "error_code": "note_too_long"}
                )
                continue

            if (not allow_notes) and ev.note.strip():
                rejected += 1
                results.append(
                    {"event_id": ev.event_id, "status": "rejected", "error_code": "notes_disabled"}
                )
                continue

            low = current_server_ts - settings.skew_window_ms
            high = current_server_ts + settings.skew_window_ms
            ts_client_effective = min(max(ev.ts_client, low), high)
            row_id = str(uuid.uuid4())
            event_row = {
                "id": row_id,
                "project_id": project_id,
                "user_id": user.user_id,
                "event_id": ev.event_id,
                "item_id": ev.item_id,
                "decision_id": ev.decision_id,
                "note": ev.note,
                "ts_client": ev.ts_client,
                "ts_client_effective": ts_client_effective,
                "ts_server": current_server_ts,
            }
            session.execute(decision_event.insert().values(**event_row))

            existing_latest = (
                session.execute(
                    select(decision_latest).where(
                        decision_latest.c.project_id == project_id,
                        decision_latest.c.user_id == user.user_id,
                        decision_latest.c.item_id == ev.item_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing_latest is None or _rank_key(event_row) > _rank_key(existing_latest):
                session.execute(
                    decision_latest.delete().where(
                        decision_latest.c.project_id == project_id,
                        decision_latest.c.user_id == user.user_id,
                        decision_latest.c.item_id == ev.item_id,
                    )
                )
                session.execute(
                    decision_latest.insert().values(
                        project_id=project_id,
                        user_id=user.user_id,
                        item_id=ev.item_id,
                        event_id=ev.event_id,
                        decision_id=ev.decision_id,
                        note=ev.note,
                        ts_client=ev.ts_client,
                        ts_client_effective=ts_client_effective,
                        ts_server=current_server_ts,
                    )
                )

            accepted += 1
            results.append({"event_id": ev.event_id, "status": "accepted"})

        session.commit()
        return {
            "acked": accepted + duplicate,
            "accepted": accepted,
            "duplicate": duplicate,
            "rejected": rejected,
            "server_ts": current_server_ts,
            "results": results,
        }


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/decisions")
def list_decisions(
    project_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    user: User = Depends(get_user),
):
    payload = _check_cursor(cursor)
    with session_scope() as session:
        project_role_or_404(session, project_id, user.user_id)
        q = select(decision_latest).where(
            decision_latest.c.project_id == project_id,
            decision_latest.c.user_id == user.user_id,
        )
        if payload:
            q = q.where(
                or_(
                    decision_latest.c.ts_server > payload["ts_server"],
                    and_(
                        decision_latest.c.ts_server == payload["ts_server"],
                        decision_latest.c.item_id > payload["item_id"],
                    ),
                )
            )
        rows = (
            session.execute(
                q.order_by(
                    decision_latest.c.ts_server.asc(), decision_latest.c.item_id.asc()
                ).limit(limit)
            )
            .mappings()
            .all()
        )
        decisions = [
            {
                "item_id": r["item_id"],
                "decision_id": r["decision_id"],
                "note": r["note"],
                "ts_client": r["ts_client"],
                "ts_server": r["ts_server"],
                "event_id": r["event_id"],
            }
            for r in rows
        ]
        next_cursor = None
        if rows:
            last = rows[-1]
            next_cursor = encode_cursor(
                {"ts_server": last["ts_server"], "item_id": last["item_id"]}, settings.cursor_ttl_ms
            )
        return {"decisions": decisions, "next_cursor": next_cursor}


def _require_export_create_role(role: str):
    if role not in {"admin", "reviewer"}:
        raise forbidden()


@app.post(f"{settings.api_prefix}/projects/{{project_id}}/exports")
def create_export(project_id: str, body: ExportCreateRequest, user: User = Depends(get_user)):
    with session_scope() as session:
        role = project_role_or_404(session, project_id, user.user_id)
        _require_export_create_role(role)

        running_count = session.execute(
            select(func.count(export_job.c.id)).where(
                export_job.c.project_id == project_id,
                export_job.c.requested_by_user_id == user.user_id,
                export_job.c.status.in_(["queued", "running"]),
            )
        ).scalar_one()
        if running_count >= settings.export_max_concurrent_per_user:
            raise validation_error("export_limit_exceeded", "Too many concurrent export jobs")

        prow = session.execute(
            select(project.c.config_json, project.c.decision_schema_json).where(
                project.c.id == project_id
            )
        ).one_or_none()
        if not prow:
            raise not_found()
        allowlist = set(prow.config_json.get("export_allowlist", []))
        for field in body.include_fields:
            if field not in allowlist:
                raise validation_error("field_not_allowlisted", f"Field not allowlisted: {field}")

        created_at = now_ms()
        export_id = str(uuid.uuid4())

        session.execute(
            export_job.insert().values(
                id=export_id,
                project_id=project_id,
                requested_by_user_id=user.user_id,
                status="running",
                mode=body.mode,
                label_policy=body.label_policy,
                format=body.format,
                filters_json=body.filters,
                include_fields_json=body.include_fields,
                created_at=created_at,
            )
        )

        rows = (
            session.execute(
                select(
                    decision_latest.c.item_id,
                    decision_latest.c.decision_id,
                    decision_latest.c.note,
                    decision_latest.c.ts_server,
                    item.c.external_id,
                    item.c.metadata_json,
                )
                .join(item, item.c.id == decision_latest.c.item_id)
                .where(decision_latest.c.project_id == project_id)
                .order_by(decision_latest.c.ts_server.asc(), decision_latest.c.item_id.asc())
            )
            .mappings()
            .all()
        )

        if len(rows) > settings.export_max_rows:
            raise validation_error("export_limit_exceeded", "Export exceeds max rows")

        out_dir = Path("data/exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        ext = "jsonl" if body.format not in {"csv", "parquet"} else body.format
        dataset_name = f"triagedeck_export_{project_id}_{stamp}.{ext}"
        dataset_path = out_dir / dataset_name

        if ext == "jsonl":
            with dataset_path.open("w", encoding="utf-8") as f:
                for r in rows:
                    obj = {
                        "item_id": r["item_id"],
                        "external_id": r["external_id"],
                        "decision_id": r["decision_id"],
                        "note": r["note"],
                        "ts_server": r["ts_server"],
                    }
                    f.write(json.dumps(obj, separators=(",", ":")) + "\n")
        elif ext == "csv":
            with dataset_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["item_id", "external_id", "decision_id", "note", "ts_server"],
                )
                writer.writeheader()
                for r in rows:
                    writer.writerow(
                        {
                            "item_id": r["item_id"],
                            "external_id": r["external_id"],
                            "decision_id": r["decision_id"],
                            "note": r["note"],
                            "ts_server": r["ts_server"],
                        }
                    )
        else:
            dataset_path.write_text(
                "parquet output not implemented in local mode\n", encoding="utf-8"
            )

        digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        manifest = {
            "snapshot_at": created_at,
            "project_id": project_id,
            "decision_schema_version": prow.decision_schema_json.get("version", 1),
            "label_policy": body.label_policy,
            "filters": body.filters,
            "row_count": len(rows),
            "sha256": digest,
        }
        manifest_path = out_dir / f"{dataset_path.stem}_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        expires_at = created_at + settings.export_ttl_ms
        session.execute(
            export_job.update()
            .where(export_job.c.id == export_id)
            .values(
                status="ready",
                manifest_json=manifest,
                file_uri=str(dataset_path),
                expires_at=expires_at,
                completed_at=now_ms(),
            )
        )
        session.commit()
        return {"export_id": export_id, "status": "queued"}


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/exports")
def list_exports(
    project_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_user),
):
    payload = _check_cursor(cursor)
    with session_scope() as session:
        project_role_or_404(session, project_id, user.user_id)
        q = select(export_job).where(export_job.c.project_id == project_id)
        if payload:
            q = q.where(
                or_(
                    export_job.c.created_at < payload["created_at"],
                    and_(
                        export_job.c.created_at == payload["created_at"],
                        export_job.c.id < payload["id"],
                    ),
                )
            )
        rows = (
            session.execute(
                q.order_by(export_job.c.created_at.desc(), export_job.c.id.desc()).limit(limit)
            )
            .mappings()
            .all()
        )
        out = [
            {
                "export_id": r["id"],
                "status": r["status"],
                "format": r["format"],
                "mode": r["mode"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        next_cursor = None
        if rows:
            last = rows[-1]
            next_cursor = encode_cursor(
                {"created_at": last["created_at"], "id": last["id"]}, settings.cursor_ttl_ms
            )
        return {"exports": out, "next_cursor": next_cursor}


@app.get(f"{settings.api_prefix}/projects/{{project_id}}/exports/{{export_id}}")
def get_export(project_id: str, export_id: str, user: User = Depends(get_user)):
    with session_scope() as session:
        role = project_role_or_404(session, project_id, user.user_id)
        row = (
            session.execute(
                select(export_job).where(
                    export_job.c.id == export_id, export_job.c.project_id == project_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise not_found()
        if role != "admin" and row["requested_by_user_id"] != user.user_id:
            raise forbidden()
        if row["expires_at"] and row["expires_at"] < now_ms():
            raise gone("export_expired", "Export has expired")
        return {
            "export_id": row["id"],
            "status": row["status"],
            "format": row["format"],
            "mode": row["mode"],
            "manifest": row["manifest_json"],
            "download_url": row["file_uri"],
            "expires_at": row["expires_at"],
        }


@app.delete(f"{settings.api_prefix}/projects/{{project_id}}/exports/{{export_id}}")
def cancel_export(project_id: str, export_id: str, user: User = Depends(get_user)):
    with session_scope() as session:
        role = project_role_or_404(session, project_id, user.user_id)
        row = (
            session.execute(
                select(export_job).where(
                    export_job.c.id == export_id, export_job.c.project_id == project_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise not_found()
        if role != "admin" and row["requested_by_user_id"] != user.user_id:
            raise forbidden()

        if row["status"] == "ready":
            raise conflict("export_ready", "Cannot cancel a ready export")
        if row["status"] in {"failed", "expired"}:
            return {"status": row["status"]}

        session.execute(
            export_job.update()
            .where(export_job.c.id == export_id)
            .values(status="failed", error_code="export_cancelled", completed_at=now_ms())
        )
        session.commit()
        return {"status": "failed", "error": {"code": "export_cancelled"}}
