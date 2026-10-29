from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from .config import settings
from .models import EvidenceFrame


class VideoProcessingError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(video_path: Path) -> dict[str, Any]:
    if not shutil.which(settings.ffprobe_bin):
        raise VideoProcessingError(f"ffprobe executable not found: {settings.ffprobe_bin}")
    cmd = [
        settings.ffprobe_bin, "-v", "error", "-show_entries", "format=duration,format_name",
        "-of", "json", str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise VideoProcessingError(f"ffprobe failed: {proc.stderr.strip()[:500]}")
    try:
        payload = json.loads(proc.stdout)
        duration = float(payload["format"]["duration"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise VideoProcessingError("Could not determine video duration") from exc
    if duration <= 0:
        raise VideoProcessingError("Video duration must be greater than zero")
    return {"duration_sec": duration, "format_name": payload.get("format", {}).get("format_name")}


def sample_timestamps(duration_sec: float, interval_sec: int, max_frames: int) -> list[float]:
    if duration_sec <= 0 or interval_sec <= 0 or max_frames <= 0:
        raise ValueError("duration_sec, interval_sec and max_frames must be positive")
    candidates = [round(t / 1000.0, 3) for t in range(0, int(duration_sec * 1000), interval_sec * 1000)]
    if not candidates:
        return [0.0]
    if len(candidates) <= max_frames:
        return candidates
    if max_frames == 1:
        return [0.0]
    # Keep temporal coverage across the full video when the frame cap is reached,
    # rather than only analyzing the first N * interval_sec seconds.
    selected_indices = [round(i * (len(candidates) - 1) / (max_frames - 1)) for i in range(max_frames)]
    return [candidates[index] for index in selected_indices]


def extract_frames(video_path: Path, job_id: str, timestamps: list[float]) -> list[EvidenceFrame]:
    if not shutil.which(settings.ffmpeg_bin):
        raise VideoProcessingError(f"ffmpeg executable not found: {settings.ffmpeg_bin}")
    out_dir = settings.jobs_dir / job_id / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[EvidenceFrame] = []
    for index, timestamp in enumerate(timestamps, start=1):
        filename = f"frame_{index:03d}.jpg"
        output = out_dir / filename
        cmd = [
            settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(output),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            raise VideoProcessingError(
                f"Frame extraction failed at {timestamp:.3f}s: {proc.stderr.strip()[:400]}"
            )
        try:
            with Image.open(output) as image:
                width, height = image.size
        except Exception as exc:
            raise VideoProcessingError(f"Extracted frame is not a valid image: {filename}") from exc
        results.append(EvidenceFrame(
            evidence_id=f"F{index:03d}",
            timestamp_sec=timestamp,
            timestamp_semantics="ffmpeg_seek_target",
            file_name=filename,
            sha256=sha256_file(output),
            width=width,
            height=height,
            source_video=video_path.name,
        ))
    return results
