from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .config import settings
from .pipeline import run_analysis
from .storage import create_job, get_job, job_dir, list_jobs, read_json, result_file, update_job, utc_now, write_json_atomic

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
app = FastAPI(title=settings.app_name, version="0.1.0", description="Evidence-linked cockpit video analysis MVP")


class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    decision: Literal["approved", "rejected"]
    notes: str | None = Field(default=None, max_length=2000)


def _validate_analysis_id(analysis_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{16}", analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found")


def _public_job(job: dict) -> dict:
    # Do not leak absolute local filesystem paths in the API.
    return {key: value for key, value in job.items() if key != "video_path"}


def safe_name(name: str | None) -> str:
    """Return a safe basename while preserving Unicode letters and the file extension.

    Browsers usually send just the basename, but normalize Windows separators too.
    Keep extension extraction independent from stem sanitization: stripping Unicode
    from a Chinese-only stem must never accidentally strip the recognized .mp4 suffix.
    """
    raw = (name or "uploaded-video.mp4").replace("\\", "/").split("/")[-1]
    # Remove control characters, but do not transliterate or delete Chinese characters.
    raw = "".join(char for char in raw if char.isprintable() and char not in '<>:"|?*')
    parsed = Path(raw)
    suffix = parsed.suffix.lower()
    stem = raw[:-len(parsed.suffix)] if parsed.suffix else raw
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._")
    stem = stem[:100] or "uploaded-video"
    # Normalize the suffix casing, and only sanitize the stem. The caller performs
    # the allow-list check on this suffix before writing the uploaded file.
    return f"{stem}{suffix}"[:120]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "cockpit-benchmark-analyzer",
        "mode": "openai_compatible_vlm" if settings.provider_enabled else "no_model",
        "ffmpeg_available": __import__("shutil").which(settings.ffmpeg_bin) is not None,
        "ffprobe_available": __import__("shutil").which(settings.ffprobe_bin) is not None,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html", media_type="text/html")


@app.post("/api/v1/analyses", status_code=202)
async def create_analysis(
    background_tasks: BackgroundTasks,
    video: Annotated[UploadFile, File(description="Local video file")],
    vehicle_make: Annotated[str | None, Form()] = None,
    vehicle_model: Annotated[str | None, Form()] = None,
    model_year: Annotated[str | None, Form()] = None,
    software_version: Annotated[str | None, Form()] = None,
    scenario: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
):
    original_name = safe_name(video.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported video extension: {extension or '(none)'}")

    analysis_id = uuid.uuid4().hex[:16]
    video_path = settings.videos_dir / f"{analysis_id}_{original_name}"
    settings.videos_dir.mkdir(parents=True, exist_ok=True)
    size_bytes = 0
    try:
        with video_path.open("wb") as out:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"Video exceeds {settings.max_upload_mb} MB limit")
                out.write(chunk)
    except Exception:
        video_path.unlink(missing_ok=True)
        raise
    finally:
        await video.close()

    if size_bytes == 0:
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    metadata = {
        "original_filename": original_name,
        "vehicle_make": vehicle_make or None,
        "vehicle_model": vehicle_model or None,
        "model_year": model_year or None,
        "software_version": software_version or None,
        "scenario": scenario or None,
        "source_url": source_url or None,
    }
    job = {
        "analysis_id": analysis_id,
        "status": "queued",
        "stage": "queued",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "video_path": str(video_path),
        "video_size_bytes": size_bytes,
        "video_metadata": metadata,
        "error": None,
    }
    create_job(job)
    background_tasks.add_task(run_analysis, analysis_id)
    return {"analysis_id": analysis_id, "status": "queued", "status_url": f"/api/v1/analyses/{analysis_id}", "report_url": f"/api/v1/analyses/{analysis_id}/report"}


@app.get("/api/v1/analyses")
def analyses(limit: int = 50):
    return {"items": [_public_job(item) for item in list_jobs(max(1, min(limit, 100)))]}


@app.get("/api/v1/analyses/{analysis_id}")
def analysis_status(analysis_id: str):
    _validate_analysis_id(analysis_id)
    job = get_job(analysis_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _public_job(job)


@app.get("/api/v1/analyses/{analysis_id}/report")
def analysis_report(analysis_id: str):
    _validate_analysis_id(analysis_id)
    job = get_job(analysis_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    path = result_file(analysis_id)
    if not path.exists():
        if job.get("status") == "failed":
            raise HTTPException(status_code=409, detail=job.get("error") or "Analysis failed")
        raise HTTPException(status_code=409, detail=f"Result not ready; current status is {job.get('status')}")
    return JSONResponse(content=__import__("json").loads(path.read_text(encoding="utf-8")))


@app.post("/api/v1/analyses/{analysis_id}/review")
def review_analysis(analysis_id: str, request: ReviewRequest):
    """Local-MVP review endpoint. Put behind authentication before any shared deployment."""
    _validate_analysis_id(analysis_id)
    job = get_job(analysis_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    path = result_file(analysis_id)
    if not path.exists():
        raise HTTPException(status_code=409, detail="Analysis report is not ready")
    report = read_json(path)
    if request.decision == "approved":
        scores = report.get("scores", [])
        if report.get("mode") == "no_model" or report.get("overall_score_100") is None or not scores or any(x.get("score") is None for x in scores):
            raise HTTPException(status_code=409, detail="Cannot approve an unscored or incomplete report")
    reviewer = request.reviewer.strip()
    if not reviewer:
        raise HTTPException(status_code=422, detail="reviewer cannot be blank")
    reviewed_at = utc_now()
    review_event = {"reviewer": reviewer, "decision": request.decision, "reviewed_at": reviewed_at, "notes": request.notes}
    report.setdefault("review_history", []).append(review_event)
    report["review_status"] = request.decision
    report["reviewer"] = reviewer
    report["reviewed_at"] = reviewed_at
    report["review_notes"] = request.notes
    write_json_atomic(path, report)
    update_job(analysis_id, review_status=request.decision, reviewer=reviewer, reviewed_at=reviewed_at)
    return {"analysis_id": analysis_id, "review_status": request.decision, "reviewer": reviewer, "reviewed_at": reviewed_at}


@app.get("/api/v1/analyses/{analysis_id}/evidence/{filename}")
def evidence_file(analysis_id: str, filename: str):
    _validate_analysis_id(analysis_id)
    if not re.fullmatch(r"frame_\d{3}\.jpg", filename):
        raise HTTPException(status_code=400, detail="Invalid evidence filename")
    job = get_job(analysis_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    path = job_dir(analysis_id) / "frames" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence frame not found")
    return FileResponse(path, media_type="image/jpeg", filename=filename)


@app.get("/api/v1/rubric")
def rubric():
    path = Path(__file__).resolve().parents[1] / "config" / "rubric.v1.json"
    return JSONResponse(content=__import__("json").loads(path.read_text(encoding="utf-8")))
