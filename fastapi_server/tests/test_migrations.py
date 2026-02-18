from __future__ import annotations

from sqlalchemy import inspect, select

from fastapi_server.db import ensure_dev_seed_users, organization, session_scope, upgrade_db


def test_migration_upgrade_fresh_db(tmp_path):
    db_path = tmp_path / "fresh.db"
    db_url = f"sqlite:///{db_path}"

    upgrade_db(db_url=db_url)

    with session_scope(db_url) as session:
        insp = inspect(session.bind)
        tables = set(insp.get_table_names())

    expected = {
        "organization",
        "organization_membership",
        "project",
        "project_membership",
        "item",
        "item_variant",
        "decision_event",
        "decision_latest",
        "export_job",
        "alembic_version",
    }
    assert expected.issubset(tables)


def test_migration_then_seed(tmp_path):
    db_path = tmp_path / "seeded.db"
    db_url = f"sqlite:///{db_path}"

    upgrade_db(db_url=db_url)
    ensure_dev_seed_users(db_url=db_url)

    with session_scope(db_url) as session:
        org_count = session.execute(select(organization.c.id)).all()
    assert len(org_count) >= 1
