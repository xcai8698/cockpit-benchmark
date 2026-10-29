from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_dir(job_id: str) -> Path:
    return settings.jobs_dir / job_id


def job_file(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def result_file(job_id: str) -> Path:
    return job_dir(job_id) / "analysis.json"


def frames_dir(job_id: str) -> Path:
    return job_dir(job_id) / "frames"


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def create_job(job: dict[str, Any]) -> None:
    job_dir(job["analysis_id"]).mkdir(parents=True, exist_ok=True)
    write_json_atomic(job_file(job["analysis_id"]), job)


def get_job(job_id: str) -> dict[str, Any] | None:
    path = job_file(job_id)
    if not path.exists():
        return None
    return read_json(path)


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Unknown analysis_id: {job_id}")
    job.update(fields)
    job["updated_at"] = utc_now()
    write_json_atomic(job_file(job_id), job)
    return job


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not settings.jobs_dir.exists():
        return items
    for path in settings.jobs_dir.glob("*/job.json"):
        try:
            items.append(read_json(path))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
