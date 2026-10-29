from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from .config import settings
from .models import EvidenceFrame


class VideoProcessingError(RuntimeError):
    pass


SAMPLING_POLICY_VERSION = "1.0.0"
SUPPORTED_SAMPLING_POLICIES = {"uniform_v1", "scene_aware_v1"}
SCENE_TIMESTAMP_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


@dataclass(frozen=True)
class SamplingPlan:
    timestamps: list[float]
    manifest: dict[str, Any]
    warnings: list[str]


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
    if not math.isfinite(duration) or duration <= 0:
        raise VideoProcessingError("Video duration must be greater than zero")
    return {"duration_sec": duration, "format_name": payload.get("format", {}).get("format_name")}


def _evenly_select(values: list[float], count: int) -> list[float]:
    """Select a deterministic spread of values, preserving order."""
    if count <= 0 or not values:
        return []
    if len(values) <= count:
        return values[:]
    if count == 1:
        return [values[0]]
    indices = [round(i * (len(values) - 1) / (count - 1)) for i in range(count)]
    return [values[index] for index in indices]


def _grid_timestamps(duration_sec: float, interval_sec: int) -> list[float]:
    return [
        round(t / 1000.0, 3)
        for t in range(0, int(duration_sec * 1000), interval_sec * 1000)
    ]


def sample_timestamps(duration_sec: float, interval_sec: int, max_frames: int) -> list[float]:
    """Legacy uniform grid sampler; kept stable for uniform_v1 reproducibility."""
    if not math.isfinite(duration_sec) or duration_sec <= 0 or interval_sec <= 0 or max_frames <= 0:
        raise ValueError("duration_sec, interval_sec and max_frames must be positive")
    candidates = _grid_timestamps(duration_sec, interval_sec)
    if not candidates:
        return [0.0]
    return _evenly_select(candidates, max_frames)


def detect_scene_changes(video_path: Path, threshold: float | None = None) -> list[float]:
    """Detect likely visual cuts on a 2-fps, 320-pixel-wide proxy stream.

    This finds coarse scene transitions, not semantic interactions or every brief
    telltale/button state change. Detection is intentionally opt-in because it
    requires an additional full decode pass.
    """
    threshold = settings.scene_change_threshold if threshold is None else threshold
    if not 0.0 < threshold < 1.0:
        raise ValueError("scene threshold must be between 0 and 1")
    if not shutil.which(settings.ffmpeg_bin):
        raise VideoProcessingError(f"ffmpeg executable not found: {settings.ffmpeg_bin}")

    filter_graph = (
        "fps=2,scale='min(320,iw)':-2,"
        f"select='gt(scene,{threshold:.3f})',showinfo"
    )
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-loglevel", "info", "-i", str(video_path),
        "-vf", filter_graph, "-an", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.scene_detection_timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError(
            f"Scene detection timed out after {settings.scene_detection_timeout_sec}s"
        ) from exc
    if proc.returncode != 0:
        raise VideoProcessingError(f"Scene detection failed: {proc.stderr.strip()[-500:]}")
    timestamps = [round(float(match.group(1)), 3) for match in SCENE_TIMESTAMP_RE.finditer(proc.stderr)]
    # Nearby hits are generally the same cut represented by adjacent sampled frames.
    deduped: list[float] = []
    for timestamp in sorted(timestamps):
        if timestamp >= 0 and (not deduped or timestamp - deduped[-1] >= 0.5):
            deduped.append(timestamp)
    return deduped


def _normalise_event_timestamps(
    values: Iterable[float], duration_sec: float
) -> tuple[list[float], list[float]]:
    valid: list[float] = []
    invalid: list[float] = []
    for raw in values:
        try:
            timestamp = float(raw)
        except (TypeError, ValueError):
            invalid.append(float("nan"))
            continue
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp >= duration_sec:
            invalid.append(timestamp)
        else:
            valid.append(round(timestamp, 3))
    return sorted(set(valid)), invalid


def _append_if_far(selected: list[float], timestamp: float, distance_sec: float = 0.25) -> bool:
    if any(abs(timestamp - item) < distance_sec for item in selected):
        return False
    selected.append(timestamp)
    selected.sort()
    return True


def _fill_spread(
    selected: list[float], candidates: list[float], limit: int
) -> list[float]:
    """Greedily add candidates furthest from already selected timestamps."""
    chosen = selected[:]
    remaining = sorted(set(candidates) - set(chosen))
    while remaining and len(chosen) < limit:
        if not chosen:
            pick = remaining[0]
        else:
            # Earlier timestamps win ties, making the result deterministic.
            pick = max(remaining, key=lambda t: (min(abs(t - item) for item in chosen), -t))
        _append_if_far(chosen, pick)
        remaining.remove(pick)
    return sorted(chosen)


def _coverage_gaps(timestamps: list[float], duration_sec: float, interval_sec: int) -> tuple[float, list[dict[str, float]]]:
    ordered = sorted(timestamps)
    edges = [0.0, *ordered, duration_sec]
    # The start/end samples themselves are not treated as uncovered intervals.
    gaps: list[dict[str, float]] = []
    threshold = interval_sec * 1.1
    for start, end in zip(edges, edges[1:]):
        gap = round(end - start, 3)
        if gap > threshold:
            gaps.append({"start_sec": round(start, 3), "end_sec": round(end, 3), "duration_sec": gap})
    max_gap = round(max((b - a for a, b in zip(ordered, ordered[1:])), default=0.0), 3)
    if ordered:
        max_gap = round(max(max_gap, ordered[0], duration_sec - ordered[-1]), 3)
    else:
        max_gap = round(duration_sec, 3)
    return max_gap, gaps


def plan_sampling(
    duration_sec: float,
    interval_sec: int,
    max_frames: int,
    *,
    policy_id: str = "uniform_v1",
    scene_change_timestamps: Iterable[float] = (),
    supplemental_timestamps: Iterable[float] = (),
    scene_threshold: float | None = None,
    scene_detection_attempted: bool = False,
    scene_detection_succeeded: bool = False,
) -> SamplingPlan:
    """Build a deterministic frame plan and an audit manifest.

    uniform_v1 preserves the historical interval-grid behavior unless manual
    supplemental timestamps are provided. scene_aware_v1 reserves some frame
    budget for detected cuts, then fills remaining slots for temporal coverage.
    """
    if not math.isfinite(duration_sec) or duration_sec <= 0 or interval_sec <= 0 or max_frames <= 0:
        raise ValueError("duration_sec, interval_sec and max_frames must be positive")
    if policy_id not in SUPPORTED_SAMPLING_POLICIES:
        raise ValueError(f"Unsupported sampling policy: {policy_id}")

    uniform = sample_timestamps(duration_sec, interval_sec, max_frames)
    grid = _grid_timestamps(duration_sec, interval_sec)
    valid_manual, invalid_manual = _normalise_event_timestamps(supplemental_timestamps, duration_sec)
    valid_scenes, invalid_scenes = _normalise_event_timestamps(scene_change_timestamps, duration_sec)
    warnings: list[str] = []
    if invalid_manual:
        warnings.append(
            f"Ignored {len(invalid_manual)} supplemental timestamp(s) outside the video duration or invalid."
        )
    if invalid_scenes:
        warnings.append(f"Ignored {len(invalid_scenes)} invalid scene-change timestamp(s).")

    requested_manual, _ = _normalise_event_timestamps(supplemental_timestamps, float("inf"))
    if len(valid_manual) > max_frames:
        used_manual = _evenly_select(valid_manual, max_frames)
        dropped_manual = [t for t in valid_manual if t not in used_manual]
        warnings.append(
            f"{len(dropped_manual)} supplemental timestamp(s) were dropped because the frame budget was exceeded."
        )
    else:
        used_manual = valid_manual
        dropped_manual = []

    selected = used_manual[:]
    selected_scenes: list[float] = []
    scene_candidates = valid_scenes if policy_id == "scene_aware_v1" else []
    available = max_frames - len(selected)
    # Cap scene cuts to roughly one third of the budget so global coverage is retained.
    scene_slots = min(available, max(1, max_frames // 3)) if available > 0 else 0
    eligible_scenes = [
        t for t in scene_candidates
        if all(abs(t - existing) >= 0.5 for existing in selected)
    ]
    selected_scenes = _evenly_select(eligible_scenes, min(scene_slots, len(eligible_scenes)))
    selected.extend(selected_scenes)
    selected = sorted(set(selected))

    if not valid_manual and not selected_scenes and policy_id == "uniform_v1":
        timestamps = uniform
    else:
        # Include the full fixed-interval grid and uniform anchors as filler candidates.
        # The farthest-point fill naturally prioritizes full-video temporal coverage.
        candidates = sorted(set(grid + uniform + valid_scenes))
        timestamps = _fill_spread(selected, candidates, max_frames)
        if not timestamps:
            timestamps = [0.0]

    max_gap, gaps = _coverage_gaps(timestamps, duration_sec, interval_sec)
    manifest = {
        "policy_id": policy_id,
        "policy_version": SAMPLING_POLICY_VERSION,
        "interval_sec": interval_sec,
        "max_frames": max_frames,
        "scene_detection_attempted": scene_detection_attempted,
        "scene_detection_succeeded": scene_detection_succeeded,
        "scene_threshold": scene_threshold if policy_id == "scene_aware_v1" else None,
        "scene_change_candidates_sec": valid_scenes if policy_id == "scene_aware_v1" else [],
        "scene_change_timestamps_used_sec": selected_scenes,
        "supplemental_timestamps_requested_sec": requested_manual,
        "supplemental_timestamps_used_sec": used_manual,
        "supplemental_timestamps_dropped_sec": dropped_manual,
        "candidate_count": len(set(grid + valid_scenes + valid_manual)),
        "selected_timestamps_sec": timestamps,
        "max_gap_sec": max_gap,
        "coverage_gaps": gaps,
    }
    return SamplingPlan(timestamps=timestamps, manifest=manifest, warnings=warnings)


def build_sampling_plan(
    video_path: Path,
    duration_sec: float,
    interval_sec: int,
    max_frames: int,
    *,
    policy_id: str = "uniform_v1",
    supplemental_timestamps: Iterable[float] = (),
) -> SamplingPlan:
    scene_candidates: list[float] = []
    attempted = policy_id == "scene_aware_v1"
    succeeded = False
    warnings: list[str] = []
    if attempted:
        try:
            scene_candidates = detect_scene_changes(video_path)
            succeeded = True
        except (VideoProcessingError, OSError, subprocess.SubprocessError) as exc:
            # Scene detection is an enhancement, not a reason to lose the baseline analysis.
            warnings.append(f"Scene detection unavailable; fell back to temporal coverage: {exc}")

    plan = plan_sampling(
        duration_sec, interval_sec, max_frames,
        policy_id=policy_id,
        scene_change_timestamps=scene_candidates,
        supplemental_timestamps=supplemental_timestamps,
        scene_threshold=settings.scene_change_threshold if attempted else None,
        scene_detection_attempted=attempted,
        scene_detection_succeeded=succeeded,
    )
    return SamplingPlan(
        timestamps=plan.timestamps,
        manifest=plan.manifest,
        warnings=warnings + plan.warnings,
    )


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
