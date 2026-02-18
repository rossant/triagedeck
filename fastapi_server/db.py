from __future__ import annotations

import argparse
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import Session

from fastapi_server.config import settings

metadata = MetaData()

organization = Table(
    "organization",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

organization_membership = Table(
    "organization_membership",
    metadata,
    Column("organization_id", String(36), ForeignKey("organization.id"), primary_key=True),
    Column("user_id", String(255), primary_key=True),
    Column("email", String(255), nullable=False),
    Column("role", String(16), nullable=False),
)

project = Table(
    "project",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), ForeignKey("organization.id"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("slug", String(255), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("deleted_at", BigInteger),
    Column("decision_schema_json", JSON, nullable=False),
    Column("config_json", JSON, nullable=False),
)

project_membership = Table(
    "project_membership",
    metadata,
    Column("project_id", String(36), ForeignKey("project.id"), primary_key=True),
    Column("user_id", String(255), primary_key=True),
    Column("role", String(16), nullable=False),
)

item = Table(
    "item",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("project.id"), nullable=False, index=True),
    Column("external_id", String(255), nullable=False),
    Column("media_type", String(16), nullable=False),
    Column("uri", Text, nullable=False),
    Column("sort_key", String(255), nullable=False, index=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("deleted_at", BigInteger),
)

item_variant = Table(
    "item_variant",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("item_id", String(36), ForeignKey("item.id"), nullable=False, index=True),
    Column("variant_key", String(64), nullable=False),
    Column("label", String(128), nullable=False),
    Column("uri", Text, nullable=False),
    Column("sort_order", Integer, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    UniqueConstraint("item_id", "variant_key", name="uq_item_variant_item_key"),
)

decision_event = Table(
    "decision_event",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("project.id"), nullable=False, index=True),
    Column("user_id", String(255), nullable=False, index=True),
    Column("event_id", String(36), nullable=False, index=True),
    Column("item_id", String(36), ForeignKey("item.id"), nullable=False),
    Column("decision_id", String(64), nullable=False),
    Column("note", String(2000), nullable=False),
    Column("ts_client", BigInteger, nullable=False),
    Column("ts_client_effective", BigInteger, nullable=False),
    Column("ts_server", BigInteger, nullable=False),
    UniqueConstraint("project_id", "user_id", "event_id", name="uq_decision_event_idempotency"),
)

decision_latest = Table(
    "decision_latest",
    metadata,
    Column("project_id", String(36), ForeignKey("project.id"), primary_key=True),
    Column("user_id", String(255), primary_key=True),
    Column("item_id", String(36), ForeignKey("item.id"), primary_key=True),
    Column("event_id", String(36), nullable=False),
    Column("decision_id", String(64), nullable=False),
    Column("note", String(2000), nullable=False),
    Column("ts_client", BigInteger, nullable=False),
    Column("ts_client_effective", BigInteger, nullable=False),
    Column("ts_server", BigInteger, nullable=False),
)

export_job = Table(
    "export_job",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("project.id"), nullable=False, index=True),
    Column("requested_by_user_id", String(255), nullable=False, index=True),
    Column("status", String(16), nullable=False, index=True),
    Column("mode", String(32), nullable=False),
    Column("label_policy", String(32), nullable=False),
    Column("format", String(16), nullable=False),
    Column("filters_json", JSON, nullable=False),
    Column("include_fields_json", JSON, nullable=False),
    Column("manifest_json", JSON),
    Column("file_uri", Text),
    Column("expires_at", BigInteger),
    Column("created_at", BigInteger, nullable=False),
    Column("completed_at", BigInteger),
    Column("error_code", String(64)),
    Column("cancel_requested", Boolean, nullable=False, default=False),
)

Index("ix_item_project_sort_itemid", item.c.project_id, item.c.sort_key, item.c.id)
Index(
    "ix_variant_item_sort_key",
    item_variant.c.item_id,
    item_variant.c.sort_order,
    item_variant.c.variant_key,
)
Index(
    "ix_decision_latest_project_user_item",
    decision_latest.c.project_id,
    decision_latest.c.user_id,
    decision_latest.c.item_id,
)
Index(
    "ix_decision_event_project_user_event",
    decision_event.c.project_id,
    decision_event.c.user_id,
    decision_event.c.event_id,
)


def get_engine():
    return create_engine(settings.db_url, future=True)


@contextmanager
def session_scope():
    engine = get_engine()
    with Session(engine) as session:
        yield session


def init_db() -> None:
    engine = get_engine()
    metadata.create_all(engine)


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def ensure_dev_seed_users() -> None:
    with session_scope() as session:
        exists = session.execute(select(organization.c.id).limit(1)).first()
        if exists:
            return
        t = now_ms()
        org_id = str(uuid.uuid4())
        project_id = str(uuid.uuid4())
        session.execute(organization.insert().values(id=org_id, name="Local Org", created_at=t))
        session.execute(
            organization_membership.insert(),
            [
                {
                    "organization_id": org_id,
                    "user_id": "admin@example.com",
                    "email": "admin@example.com",
                    "role": "admin",
                },
                {
                    "organization_id": org_id,
                    "user_id": "reviewer@example.com",
                    "email": "reviewer@example.com",
                    "role": "reviewer",
                },
                {
                    "organization_id": org_id,
                    "user_id": "viewer@example.com",
                    "email": "viewer@example.com",
                    "role": "viewer",
                },
            ],
        )
        schema = {
            "version": 1,
            "choices": [
                {"id": "pass", "label": "PASS", "hotkey": "p"},
                {"id": "fail", "label": "FAIL", "hotkey": "f"},
            ],
            "allow_notes": True,
        }
        config = {
            "media_types_supported": ["image", "video", "pdf"],
            "variants_enabled": True,
            "variant_navigation_mode": "both",
            "compare_mode_enabled": True,
            "max_compare_variants": 2,
            "export_allowlist": [
                "item_id",
                "external_id",
                "decision_id",
                "note",
                "ts_server",
                "variant_key",
                "metadata.subject_id",
                "metadata.session_id",
            ],
        }
        session.execute(
            project.insert().values(
                id=project_id,
                organization_id=org_id,
                name="Demo Project",
                slug="demo-project",
                created_at=t,
                decision_schema_json=schema,
                config_json=config,
            )
        )
        session.execute(
            project_membership.insert(),
            [
                {"project_id": project_id, "user_id": "admin@example.com", "role": "admin"},
                {"project_id": project_id, "user_id": "reviewer@example.com", "role": "reviewer"},
                {"project_id": project_id, "user_id": "viewer@example.com", "role": "viewer"},
            ],
        )
        for i in range(1, 21):
            item_id = str(uuid.uuid4())
            external_id = f"img_{i:04d}"
            session.execute(
                item.insert().values(
                    id=item_id,
                    project_id=project_id,
                    external_id=external_id,
                    media_type="image",
                    uri=f"/media/{external_id}.jpg",
                    sort_key=f"{i:08d}",
                    metadata_json={
                        "subject_id": f"subject-{(i % 3) + 1}",
                        "session_id": f"s-{(i % 5) + 1}",
                    },
                    created_at=t,
                )
            )
            session.execute(
                item_variant.insert(),
                [
                    {
                        "id": str(uuid.uuid4()),
                        "item_id": item_id,
                        "variant_key": "before",
                        "label": "Before",
                        "uri": f"/media/{external_id}_before.jpg",
                        "sort_order": 10,
                        "metadata_json": {},
                        "created_at": t,
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "item_id": item_id,
                        "variant_key": "after",
                        "label": "After",
                        "uri": f"/media/{external_id}_after.jpg",
                        "sort_order": 20,
                        "metadata_json": {},
                        "created_at": t,
                    },
                ],
            )
        session.commit()


def _cli() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    args = parser.parse_args()
    if args.command == "init":
        init_db()


if __name__ == "__main__":
    _cli()
