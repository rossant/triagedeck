from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_id: str
    item_id: str
    decision_id: str
    note: str = ""
    ts_client: int


class EventsIngestRequest(BaseModel):
    client_id: str
    session_id: str
    events: list[EventIn] = Field(default_factory=list, max_length=200)


class ExportCreateRequest(BaseModel):
    mode: str = "labels_only"
    label_policy: str = "latest_per_user"
    format: str = "jsonl"
    filters: dict[str, Any] = Field(default_factory=dict)
    include_fields: list[str] = Field(default_factory=list)
