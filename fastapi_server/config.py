from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_prefix: str = "/api/v1"
    db_url: str = os.getenv("TRIAGEDECK_DB_URL", "sqlite:///data/triagedeck.db")
    skew_window_ms: int = int(os.getenv("TRIAGEDECK_SKEW_WINDOW_MS", 24 * 60 * 60 * 1000))
    cursor_ttl_ms: int = int(os.getenv("TRIAGEDECK_CURSOR_TTL_MS", 7 * 24 * 60 * 60 * 1000))
    signed_url_ttl_s: int = int(os.getenv("TRIAGEDECK_SIGNED_URL_TTL_S", 15 * 60))
    export_ttl_ms: int = int(os.getenv("TRIAGEDECK_EXPORT_TTL_MS", 7 * 24 * 60 * 60 * 1000))
    export_max_rows: int = int(os.getenv("TRIAGEDECK_EXPORT_MAX_ROWS", 1_000_000))
    export_max_bytes: int = int(os.getenv("TRIAGEDECK_EXPORT_MAX_BYTES", 5 * 1024 * 1024 * 1024))
    export_max_concurrent_per_user: int = int(
        os.getenv("TRIAGEDECK_EXPORT_MAX_CONCURRENT_PER_USER", 2)
    )


settings = Settings()
