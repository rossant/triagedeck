from __future__ import annotations

from dataclasses import dataclass

from fastapi_server.db import now_ms


@dataclass(frozen=True)
class ResolvedURL:
    uri: str
    expires_at: int


class StorageResolver:
    def resolve(self, logical_uri: str, ttl_s: int) -> ResolvedURL:
        return ResolvedURL(uri=logical_uri, expires_at=now_ms() + (ttl_s * 1000))
