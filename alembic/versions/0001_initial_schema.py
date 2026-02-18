"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-02-18 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "organization_membership",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )

    op.create_table(
        "project",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.BigInteger(), nullable=True),
        sa.Column("decision_schema_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "project_membership",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )

    op.create_table(
        "item",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("sort_key", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_project_id", "item", ["project_id"], unique=False)
    op.create_index("ix_item_sort_key", "item", ["sort_key"], unique=False)
    op.create_index("ix_item_project_sort_itemid", "item", ["project_id", "sort_key", "id"], unique=False)

    op.create_table(
        "item_variant",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("variant_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "variant_key", name="uq_item_variant_item_key"),
    )
    op.create_index("ix_item_variant_item_id", "item_variant", ["item_id"], unique=False)
    op.create_index(
        "ix_variant_item_sort_key",
        "item_variant",
        ["item_id", "sort_order", "variant_key"],
        unique=False,
    )

    op.create_table(
        "decision_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=False),
        sa.Column("ts_client", sa.BigInteger(), nullable=False),
        sa.Column("ts_client_effective", sa.BigInteger(), nullable=False),
        sa.Column("ts_server", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", "event_id", name="uq_decision_event_idempotency"),
    )
    op.create_index("ix_decision_event_event_id", "decision_event", ["event_id"], unique=False)
    op.create_index("ix_decision_event_project_id", "decision_event", ["project_id"], unique=False)
    op.create_index("ix_decision_event_user_id", "decision_event", ["user_id"], unique=False)
    op.create_index(
        "ix_decision_event_project_user_event",
        "decision_event",
        ["project_id", "user_id", "event_id"],
        unique=False,
    )

    op.create_table(
        "decision_latest",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=False),
        sa.Column("ts_client", sa.BigInteger(), nullable=False),
        sa.Column("ts_client_effective", sa.BigInteger(), nullable=False),
        sa.Column("ts_server", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("project_id", "user_id", "item_id"),
    )
    op.create_index(
        "ix_decision_latest_project_user_item",
        "decision_latest",
        ["project_id", "user_id", "item_id"],
        unique=False,
    )

    op.create_table(
        "export_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("label_policy", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("include_fields_json", sa.JSON(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=True),
        sa.Column("file_uri", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("completed_at", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_job_project_id", "export_job", ["project_id"], unique=False)
    op.create_index("ix_export_job_requested_by_user_id", "export_job", ["requested_by_user_id"], unique=False)
    op.create_index("ix_export_job_status", "export_job", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_export_job_status", table_name="export_job")
    op.drop_index("ix_export_job_requested_by_user_id", table_name="export_job")
    op.drop_index("ix_export_job_project_id", table_name="export_job")
    op.drop_table("export_job")

    op.drop_index("ix_decision_latest_project_user_item", table_name="decision_latest")
    op.drop_table("decision_latest")

    op.drop_index("ix_decision_event_project_user_event", table_name="decision_event")
    op.drop_index("ix_decision_event_user_id", table_name="decision_event")
    op.drop_index("ix_decision_event_project_id", table_name="decision_event")
    op.drop_index("ix_decision_event_event_id", table_name="decision_event")
    op.drop_table("decision_event")

    op.drop_index("ix_variant_item_sort_key", table_name="item_variant")
    op.drop_index("ix_item_variant_item_id", table_name="item_variant")
    op.drop_table("item_variant")

    op.drop_index("ix_item_project_sort_itemid", table_name="item")
    op.drop_index("ix_item_sort_key", table_name="item")
    op.drop_index("ix_item_project_id", table_name="item")
    op.drop_table("item")

    op.drop_table("project_membership")
    op.drop_table("project")
    op.drop_table("organization_membership")
    op.drop_table("organization")
