from __future__ import annotations

import json
import uuid

import pytest

from django_app.models import ExportJob, Item, Organization, Project, ProjectMembership, Role


@pytest.fixture()
def reviewer(django_user_model):
    return django_user_model.objects.create_user(
        username="reviewer",
        email="reviewer@example.com",
        password="pw",
    )


@pytest.fixture()
def viewer(django_user_model):
    return django_user_model.objects.create_user(
        username="viewer",
        email="viewer@example.com",
        password="pw",
    )


@pytest.fixture()
def admin(django_user_model):
    return django_user_model.objects.create_user(
        username="admin",
        email="admin@example.com",
        password="pw",
    )


@pytest.fixture()
def seeded_project(reviewer, viewer, admin):
    org = Organization.objects.create(name="Org")
    project = Project.objects.create(
        organization=org,
        name="Demo",
        slug="demo",
        decision_schema_json={
            "version": 1,
            "choices": [
                {"id": "pass", "label": "PASS", "hotkey": "p"},
                {"id": "fail", "label": "FAIL", "hotkey": "f"},
            ],
            "allow_notes": True,
        },
        config_json={
            "media_types_supported": ["image"],
            "variants_enabled": True,
            "variant_navigation_mode": "both",
            "compare_mode_enabled": True,
            "max_compare_variants": 2,
            "export_allowlist": ["item_id", "external_id", "decision_id", "note", "ts_server"],
        },
    )
    ProjectMembership.objects.create(project=project, user=reviewer, role=Role.REVIEWER)
    ProjectMembership.objects.create(project=project, user=viewer, role=Role.VIEWER)
    ProjectMembership.objects.create(project=project, user=admin, role=Role.ADMIN)

    item = Item.objects.create(
        project=project,
        external_id="img_0001",
        media_type=Item.MEDIA_IMAGE,
        uri="/media/img_0001.jpg",
        sort_key="00000001",
        metadata_json={"subject_id": "s1"},
    )
    return {
        "project": project,
        "item": item,
    }


@pytest.mark.django_db
def test_projects_requires_auth(client, seeded_project):
    response = client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.django_db
def test_projects_list(client, reviewer, seeded_project):
    client.force_login(reviewer)
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    assert len(response.json()["projects"]) == 1


@pytest.mark.django_db
def test_items_invalid_cursor(client, reviewer, seeded_project):
    project = seeded_project["project"]
    client.force_login(reviewer)
    response = client.get(f"/api/v1/projects/{project.id}/items?cursor=bad")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.django_db
def test_viewer_cannot_post_events(client, viewer, seeded_project):
    project = seeded_project["project"]
    item = seeded_project["item"]

    client.force_login(viewer)
    payload = {
        "client_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "events": [
            {
                "event_id": str(uuid.uuid4()),
                "item_id": str(item.id),
                "decision_id": "pass",
                "note": "",
                "ts_client": 1739472000000,
            }
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project.id}/events",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.django_db
def test_reviewer_event_idempotency(client, reviewer, seeded_project):
    project = seeded_project["project"]
    item = seeded_project["item"]

    client.force_login(reviewer)
    event_id = str(uuid.uuid4())
    payload = {
        "client_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "events": [
            {
                "event_id": event_id,
                "item_id": str(item.id),
                "decision_id": "pass",
                "note": "ok",
                "ts_client": 1739472000000,
            }
        ],
    }
    r1 = client.post(
        f"/api/v1/projects/{project.id}/events",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r1.status_code == 200
    assert r1.json()["accepted"] == 1

    r2 = client.post(
        f"/api/v1/projects/{project.id}/events",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r2.status_code == 200
    assert r2.json()["duplicate"] == 1


@pytest.mark.django_db
def test_export_allowlist_enforced(client, reviewer, seeded_project):
    project = seeded_project["project"]
    client.force_login(reviewer)
    response = client.post(
        f"/api/v1/projects/{project.id}/exports",
        data=json.dumps(
            {
                "mode": "labels_only",
                "label_policy": "latest_per_user",
                "format": "jsonl",
                "filters": {},
                "include_fields": ["metadata.secret_field"],
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "field_not_allowlisted"


@pytest.mark.django_db
def test_export_cancel_ready_conflict(client, reviewer, seeded_project):
    project = seeded_project["project"]
    client.force_login(reviewer)
    create = client.post(
        f"/api/v1/projects/{project.id}/exports",
        data=json.dumps(
            {
                "mode": "labels_only",
                "label_policy": "latest_per_user",
                "format": "jsonl",
                "filters": {},
                "include_fields": ["item_id", "external_id", "decision_id", "note", "ts_server"],
            }
        ),
        content_type="application/json",
    )
    export_id = create.json()["export_id"]
    cancel = client.delete(f"/api/v1/projects/{project.id}/exports/{export_id}")
    assert cancel.status_code == 409
    assert cancel.json()["error"]["code"] == "export_ready"


@pytest.mark.django_db
def test_export_access_scope_creator_vs_admin(client, reviewer, viewer, admin, seeded_project):
    project = seeded_project["project"]

    client.force_login(reviewer)
    create = client.post(
        f"/api/v1/projects/{project.id}/exports",
        data=json.dumps(
            {
                "mode": "labels_only",
                "label_policy": "latest_per_user",
                "format": "jsonl",
                "filters": {},
                "include_fields": ["item_id", "external_id", "decision_id", "note", "ts_server"],
            }
        ),
        content_type="application/json",
    )
    export_id = create.json()["export_id"]

    client.force_login(viewer)
    forbidden = client.get(f"/api/v1/projects/{project.id}/exports/{export_id}")
    assert forbidden.status_code == 403

    client.force_login(admin)
    allowed = client.get(f"/api/v1/projects/{project.id}/exports/{export_id}")
    assert allowed.status_code == 200
    assert allowed.json()["export_id"] == export_id


@pytest.mark.django_db
def test_export_expiry_behavior(client, reviewer, seeded_project):
    project = seeded_project["project"]
    client.force_login(reviewer)
    create = client.post(
        f"/api/v1/projects/{project.id}/exports",
        data=json.dumps(
            {
                "mode": "labels_only",
                "label_policy": "latest_per_user",
                "format": "jsonl",
                "filters": {},
                "include_fields": ["item_id", "external_id", "decision_id", "note", "ts_server"],
            }
        ),
        content_type="application/json",
    )
    export_id = create.json()["export_id"]
    ExportJob.objects.filter(id=export_id).update(expires_at=1)
    expired = client.get(f"/api/v1/projects/{project.id}/exports/{export_id}")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "export_expired"
