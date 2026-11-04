from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import settings
from .audio import AudioProcessingError, prepare_audio
from .models import AnalysisResult, AudioManifest, MetricScore, Observation, SamplingManifest, VideoMetadata
from .providers.openai_compatible import ProviderError, analyze_frames
from .storage import get_job, result_file, update_job, utc_now, write_json_atomic
from .video import build_sampling_plan, extract_frames, probe_video

RUBRIC_PATH = Path(__file__).resolve().parents[1] / "config" / "rubric.v1.json"


def load_rubric() -> dict[str, Any]:
    with RUBRIC_PATH.open("r", encoding="utf-8") as f:
        rubric = json.load(f)
    total = sum(float(m["weight"]) for m in rubric["metrics"])
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"Rubric weights must sum to 1.0; got {total}")
    return rubric


def _normalise_model_output(
    raw: dict[str, Any], *, frames: list[dict[str, Any]], rubric: dict[str, Any]
) -> tuple[list[Observation], list[MetricScore], list[str]]:
    valid_evidence_ids = {frame["evidence_id"] for frame in frames}
    metric_by_id = {metric["metric_id"]: metric for metric in rubric["metrics"]}
    warnings: list[str] = []
    observations: list[Observation] = []
    scores_by_id: dict[str, MetricScore] = {}

    raw_observations = raw.get("observations", [])
    if not isinstance(raw_observations, list):
        warnings.append("VLM observations field was not a list; observations discarded.")
        raw_observations = []
    for item in raw_observations:
        if not isinstance(item, dict):
            continue
        evidence_id = item.get("evidence_id")
        observation = item.get("observation")
        if evidence_id not in valid_evidence_ids:
            warnings.append(f"Discarded observation with unknown evidence_id: {evidence_id!r}.")
            continue
        if not isinstance(observation, str) or not observation.strip():
            continue
        confidence = item.get("confidence")
        try:
            observations.append(Observation(
                evidence_id=evidence_id,
                observation=observation.strip()[:1200],
                confidence=float(confidence) if confidence is not None else None,
            ))
        except (ValidationError, ValueError, TypeError):
            warnings.append(f"Discarded malformed observation for {evidence_id}.")

    raw_scores = raw.get("scores", [])
    if not isinstance(raw_scores, list):
        warnings.append("VLM scores field was not a list; all scores set to evidence_insufficient.")
        raw_scores = []
    for item in raw_scores:
        if not isinstance(item, dict):
            continue
        metric_id = item.get("metric_id")
        if metric_id not in metric_by_id:
            warnings.append(f"Discarded score for unknown metric_id: {metric_id!r}.")
            continue
        if metric_id in scores_by_id:
            warnings.append(f"Discarded duplicate score for metric_id: {metric_id}.")
            continue
        metric = metric_by_id[metric_id]
        supplied_ids = item.get("evidence_ids", [])
        if not isinstance(supplied_ids, list):
            supplied_ids = []
        evidence_ids = [x for x in supplied_ids if isinstance(x, str)]
        score = item.get("score")
        rationale = item.get("rationale") if isinstance(item.get("rationale"), str) else ""
        invalid_refs = [x for x in evidence_ids if x not in valid_evidence_ids]
        if score is not None and (invalid_refs or not evidence_ids or type(score) is not int or not 1 <= score <= 5):
            warnings.append(f"Score for {metric_id} downgraded: missing/invalid evidence reference or score.")
            score = None
            evidence_ids = [x for x in evidence_ids if x in valid_evidence_ids]
        if score is None:
            status = "evidence_insufficient"
            if not rationale:
                rationale = "视频证据不足，未给分。"
            # No numeric rating is allowed to survive this branch.
        else:
            status = "scored"
            if not rationale.strip():
                warnings.append(f"Score for {metric_id} downgraded: rationale missing.")
                score = None
                status = "evidence_insufficient"
                rationale = "评分理由缺失，已降级为证据不足。"
        try:
            scores_by_id[metric_id] = MetricScore(
                metric_id=metric_id,
                score=score,
                status=status,
                rationale=rationale[:1200],
                evidence_ids=evidence_ids,
                weight=float(metric["weight"]),
            )
        except ValidationError:
            warnings.append(f"Score for {metric_id} failed schema validation and was discarded.")

    # Ensure every rubric metric is present even if model omitted it.
    scores: list[MetricScore] = []
    for metric in rubric["metrics"]:
        score = scores_by_id.get(metric["metric_id"])
        if score is None:
            score = MetricScore(
                metric_id=metric["metric_id"],
                score=None,
                status="evidence_insufficient",
                rationale="模型没有返回该指标的有效评分。",
                evidence_ids=[],
                weight=float(metric["weight"]),
            )
        scores.append(score)
    return observations, scores, warnings


def _build_av_timeline(
    frames: list[Any], audio_manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for frame in frames:
        events.append({
            "event_type": "visual_frame",
            "modality": "visual",
            "start_sec": frame.timestamp_sec,
            "end_sec": frame.timestamp_sec,
            "description": f"Visual evidence frame {frame.evidence_id}",
            "evidence_refs": [frame.evidence_id],
            "timestamp_precision": "seek_target",
        })

    chunks = audio_manifest.get("chunks", [])
    for segment in audio_manifest.get("transcript_segments", []):
        events.append({
            "event_type": "speech_transcript",
            "modality": "audio",
            "start_sec": segment["start_sec"],
            "end_sec": segment["end_sec"],
            "description": segment["text"],
            "evidence_refs": [segment["transcript_id"], segment["source_chunk_id"]],
            "timestamp_precision": (
                "asr_segment" if segment.get("timestamp_precision") == "asr_segment"
                else "chunk_window"
            ),
        })

    metrics = audio_manifest.get("signal_metrics", {})
    for silence in metrics.get("silence_intervals", []):
        start = float(silence["start_sec"])
        end = float(silence["end_sec"])
        chunk_refs = [
            chunk["chunk_id"] for chunk in chunks
            if float(chunk["start_sec"]) <= start < float(chunk["end_sec"])
        ]
        events.append({
            "event_type": "audio_silence",
            "modality": "audio",
            "start_sec": start,
            "end_sec": end,
            "description": f"Near-silence detected ({float(silence['duration_sec']):.2f}s, threshold -50 dBFS)",
            "evidence_refs": chunk_refs,
            "timestamp_precision": "signal_interval",
        })

    events.sort(key=lambda item: (item["start_sec"], item["end_sec"], item["modality"]))
    for index, event in enumerate(events, start=1):
        event["event_id"] = f"EV{index:05d}"
    return events


def run_analysis(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    update_job(job_id, status="processing", stage="probing_video", error=None)
    try:
        video_path = Path(job["video_path"])
        if not video_path.exists():
            raise FileNotFoundError("Uploaded video file no longer exists")
        probe = probe_video(video_path)
        if float(probe["duration_sec"]) > settings.max_video_duration_sec:
            raise ValueError(
                f"Video duration {float(probe['duration_sec']):.1f}s exceeds "
                f"MAX_VIDEO_DURATION_SEC={settings.max_video_duration_sec}"
            )
        sampling_options = job.get("sampling_options") or {}
        sampling_plan = build_sampling_plan(
            video_path,
            float(probe["duration_sec"]),
            settings.sample_interval_sec,
            settings.max_frames,
            policy_id=settings.sampling_policy,
            supplemental_timestamps=sampling_options.get("supplemental_timestamps_sec", []),
        )
        timestamps = sampling_plan.timestamps
        update_job(
            job_id,
            stage="extracting_frames",
            duration_sec=probe["duration_sec"],
            sampling_policy_id=sampling_plan.manifest["policy_id"],
            sampling_frame_count=len(timestamps),
        )
        evidence_models = extract_frames(video_path, job_id, timestamps)

        update_job(job_id, stage="extracting_audio", audio_status="processing")
        try:
            audio_manifest_data, audio_warnings = prepare_audio(
                video_path,
                job_id,
                audio_stream=probe.get("audio_stream"),
                duration_sec=float(probe["duration_sec"]),
            )
        except Exception as exc:
            # A broken or unsupported audio track must not discard otherwise valid visual evidence.
            audio_manifest_data = {
                "available": bool(probe.get("audio_stream")),
                "transcription_status": "failed",
                "chunks": [],
                "transcript_segments": [],
            }
            audio_warnings = [f"Audio processing failed; visual analysis continues: {type(exc).__name__}: {exc}"]
        update_job(
            job_id,
            audio_status=audio_manifest_data.get("transcription_status", "not_configured"),
            audio_chunks_count=len(audio_manifest_data.get("chunks", [])),
            transcript_segments_count=len(audio_manifest_data.get("transcript_segments", [])),
        )
        frames_dir = settings.jobs_dir / job_id / "frames"
        frames_for_model = [
            {
                "evidence_id": frame.evidence_id,
                "timestamp_sec": frame.timestamp_sec,
                "absolute_path": str(frames_dir / frame.file_name),
            }
            for frame in evidence_models
        ]
        rubric = load_rubric()
        metadata = VideoMetadata(**job["video_metadata"])
        warnings: list[str] = list(sampling_plan.warnings) + audio_warnings

        if settings.provider_enabled:
            update_job(job_id, stage="vlm_analysis")
            raw = analyze_frames(frames=frames_for_model, rubric=rubric, metadata=metadata.model_dump())
            observations, scores, normalisation_warnings = _normalise_model_output(
                raw, frames=frames_for_model, rubric=rubric
            )
            warnings.extend(normalisation_warnings)
            mode = "openai_compatible_vlm"
            model_name = settings.vlm_model
        else:
            observations = []
            scores = [
                MetricScore(
                    metric_id=metric["metric_id"], score=None,
                    status="evidence_insufficient",
                    rationale="未配置 VLM；当前仅验证上传、抽帧和证据链，不能对座舱体验打分。",
                    evidence_ids=[], weight=float(metric["weight"]),
                )
                for metric in rubric["metrics"]
            ]
            warnings.append("No VLM configured. Frames were extracted, but no visual interpretation or scoring was attempted.")
            mode = "no_model"
            model_name = None

        known_evidence_ids = {frame.evidence_id for frame in evidence_models}
        for score in scores:
            if any(evidence_id not in known_evidence_ids for evidence_id in score.evidence_ids):
                raise ValueError(f"Internal evidence reference mismatch for metric {score.metric_id}")

        overall = None
        if scores and all(score.score is not None for score in scores):
            overall = round(sum((score.score / 5.0) * score.weight * 100 for score in scores), 2)

        result = AnalysisResult(
            analysis_id=job_id,
            created_at=utc_now(),
            mode=mode,
            model_name=model_name,
            rubric_id=rubric["rubric_id"],
            rubric_version=rubric["version"],
            video_metadata=metadata,
            duration_sec=float(probe["duration_sec"]),
            media_info={
                "format_name": probe.get("format_name"),
                "size_bytes": probe.get("size_bytes"),
                "bit_rate": probe.get("bit_rate"),
                "video_stream": probe.get("video_stream"),
                "audio_stream": probe.get("audio_stream"),
                "audio_stream_count": probe.get("audio_stream_count", 0),
                "video_stream_count": probe.get("video_stream_count", 0),
            },
            sampled_frames=evidence_models,
            audio_manifest=AudioManifest(**audio_manifest_data),
            av_timeline=_build_av_timeline(evidence_models, audio_manifest_data),
            sampling_manifest=SamplingManifest(**sampling_plan.manifest),
            observations=observations,
            scores=scores,
            overall_score_100=overall,
            warnings=warnings,
            review_status="pending",
        )
        write_json_atomic(result_file(job_id), result.model_dump(mode="json"))
        final_status = "completed" if mode == "openai_compatible_vlm" else "completed_unscored"
        update_job(
            job_id,
            status=final_status,
            stage="awaiting_human_review",
            completed_at=utc_now(),
            result_url=f"/api/v1/analyses/{job_id}/report",
            frames_count=len(evidence_models),
            warning_count=len(warnings),
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            stage="failed",
            error=f"{type(exc).__name__}: {str(exc)[:1000]}",
            completed_at=utc_now(),
        )
