from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExportArtifact:
    file_uri: str
    file_path: Path
    manifest_path: Path
    row_count: int
    sha256: str
    size_bytes: int


class ExportStorage:
    def __init__(self, base_dir: Path | None = None, audit_log_path: Path | None = None):
        self.base_dir = base_dir or Path("data/exports")
        self.audit_log_path = audit_log_path or Path("data/exports/audit.log")

    def _dataset_name(self, project_id: str, snapshot_at: int, fmt: str) -> str:
        ext = "jsonl" if fmt not in {"jsonl", "csv", "parquet"} else fmt
        return f"triagedeck_export_{project_id}_{snapshot_at}.{ext}"

    def _manifest_name(self, dataset_name: str) -> str:
        stem = dataset_name.rsplit(".", 1)[0]
        return f"{stem}_manifest.json"

    def _jsonl_bytes(self, rows: list[dict[str, Any]]) -> bytes:
        lines = [json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows]
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    def _csv_bytes(self, rows: list[dict[str, Any]], include_fields: list[str]) -> bytes:
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=include_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in include_fields})
        return buf.getvalue().encode("utf-8")

    def write_bundle(
        self,
        *,
        project_id: str,
        snapshot_at: int,
        fmt: str,
        include_fields: list[str],
        rows: list[dict[str, Any]],
        manifest: dict[str, Any],
    ) -> ExportArtifact:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        dataset_name = self._dataset_name(project_id, snapshot_at, fmt)
        dataset_path = self.base_dir / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        ext = dataset_name.rsplit(".", 1)[-1]
        if ext == "jsonl":
            dataset_bytes = self._jsonl_bytes(rows)
        elif ext == "csv":
            dataset_bytes = self._csv_bytes(rows, include_fields)
        else:
            dataset_bytes = b"parquet output not implemented in local mode\n"
        dataset_path.write_bytes(dataset_bytes)

        digest = hashlib.sha256(dataset_bytes).hexdigest()
        manifest_name = self._manifest_name(dataset_name)
        manifest_path = self.base_dir / manifest_name
        full_manifest = dict(manifest)
        full_manifest["sha256"] = digest
        manifest_path.write_text(
            json.dumps(full_manifest, indent=2, sort_keys=True), encoding="utf-8"
        )

        return ExportArtifact(
            file_uri=f"/exports/{dataset_name}",
            file_path=dataset_path,
            manifest_path=manifest_path,
            row_count=len(rows),
            sha256=digest,
            size_bytes=len(dataset_bytes),
        )

    def remove_artifacts_for_uri(self, file_uri: str) -> None:
        filename = file_uri.rsplit("/", 1)[-1]
        if not filename:
            return
        dataset_path = self.base_dir / filename
        manifest_path = self.base_dir / self._manifest_name(filename)
        if dataset_path.exists():
            dataset_path.unlink()
        if manifest_path.exists():
            manifest_path.unlink()

    def audit(self, action: str, payload: dict[str, Any]) -> None:
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"action": action, "payload": payload}
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
