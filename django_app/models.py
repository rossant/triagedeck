from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Role:
    ADMIN = "admin"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    CHOICES = [
        (ADMIN, "Admin"),
        (REVIEWER, "Reviewer"),
        (VIEWER, "Viewer"),
    ]


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)


class OrganizationMembership(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.CHOICES)

    class Meta:
        unique_together = [("organization", "user")]


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    decision_schema_json = models.JSONField(default=dict)
    config_json = models.JSONField(default=dict)


class ProjectMembership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.CHOICES)

    class Meta:
        unique_together = [("project", "user")]


class Item(models.Model):
    MEDIA_IMAGE = "image"
    MEDIA_VIDEO = "video"
    MEDIA_PDF = "pdf"
    MEDIA_OTHER = "other"
    MEDIA_CHOICES = [
        (MEDIA_IMAGE, "Image"),
        (MEDIA_VIDEO, "Video"),
        (MEDIA_PDF, "PDF"),
        (MEDIA_OTHER, "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    external_id = models.CharField(max_length=255)
    media_type = models.CharField(max_length=16, choices=MEDIA_CHOICES)
    uri = models.TextField()
    sort_key = models.CharField(max_length=255)
    metadata_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "sort_key", "id"]),
        ]


class ItemVariant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    variant_key = models.CharField(max_length=64)
    label = models.CharField(max_length=128)
    uri = models.TextField()
    sort_order = models.IntegerField()
    metadata_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("item", "variant_key")]
        indexes = [
            models.Index(fields=["item", "sort_order", "variant_key"]),
        ]


class DecisionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event_id = models.UUIDField()
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    decision_id = models.CharField(max_length=64)
    note = models.CharField(max_length=2000, blank=True)
    ts_client = models.BigIntegerField()
    ts_client_effective = models.BigIntegerField()
    ts_server = models.BigIntegerField()

    class Meta:
        unique_together = [("project", "user", "event_id")]
        indexes = [
            models.Index(fields=["project", "user", "event_id"]),
        ]


class DecisionLatest(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    event_id = models.UUIDField()
    decision_id = models.CharField(max_length=64)
    note = models.CharField(max_length=2000, blank=True)
    ts_client = models.BigIntegerField()
    ts_client_effective = models.BigIntegerField()
    ts_server = models.BigIntegerField()

    class Meta:
        unique_together = [("project", "user", "item")]
        indexes = [
            models.Index(fields=["project", "user", "item"]),
        ]


class ExportJob(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    MODE_LABELS_ONLY = "labels_only"
    MODE_LABELS_PLUS_UNLABELED = "labels_plus_unlabeled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    requested_by_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    mode = models.CharField(max_length=32, default=MODE_LABELS_ONLY)
    label_policy = models.CharField(max_length=32, default="latest_per_user")
    format = models.CharField(max_length=16, default="jsonl")
    filters_json = models.JSONField(default=dict)
    include_fields_json = models.JSONField(default=list)
    manifest_json = models.JSONField(null=True, blank=True)
    file_uri = models.TextField(blank=True)
    expires_at = models.BigIntegerField(null=True, blank=True)
    created_at = models.BigIntegerField()
    completed_at = models.BigIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "created_at", "id"]),
        ]
