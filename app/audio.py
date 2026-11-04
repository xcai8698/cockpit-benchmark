from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

from .config import settings
from .video import sha256_file


class AudioProcessingError(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AudioProcessingError(f"Audio processing timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise AudioProcessingError(f"Audio processing failed: {result.stderr.strip()[-600:]}")
    return result


def _audio_signal_stats(wav_path: Path, timeout: int) -> dict[str, Any]:
    """Extract conservative signal-level indicators; these are not semantic audio judgments."""
    command = [
        settings.ffmpeg_bin, "-hide_banner", "-nostats", "-i", str(wav_path),
        "-vn", "-af", "astats=metadata=1:reset=0,silencedetect=noise=-50dB:d=0.3",
        "-f", "null", "-",
    ]
    result = _run(command, timeout=timeout)
    stderr = result.stderr
    peak_values = re.findall(r"Peak level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))", stderr, flags=re.I)
    rms_values = re.findall(r"RMS level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))", stderr, flags=re.I)
    # astats prints channel sections followed by Overall; take the final summary value.
    peak_dbfs = float(peak_values[-1]) if peak_values and peak_values[-1].lower() != "inf" else None
    rms_dbfs = float(rms_values[-1]) if rms_values and rms_values[-1].lower() != "inf" else None

    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]
    intervals: list[dict[str, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        if end is not None and end >= start:
            intervals.append({
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "duration_sec": round(end - start, 3),
            })
    return {
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": rms_dbfs,
        "silence_threshold_dbfs": -50.0,
        "silence_min_duration_sec": 0.3,
        "silence_intervals": intervals,
        "silence_interval_count": len(intervals),
        "note": "Signal-level indicators only; not a judgment of loudness appropriateness, sound quality, or semantic correctness.",
    }


def _write_chunks(
    source_wav: Path,
    output_dir: Path,
    *,
    chunk_duration_sec: int,
    overlap_sec: float,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    with wave.open(str(source_wav), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        duration = frame_count / float(sample_rate)
        if sample_width != 2:
            raise AudioProcessingError(f"Expected 16-bit PCM analysis audio, got {sample_width * 8}-bit")
        if sample_rate != 16000 or channels != 1:
            raise AudioProcessingError("Expected mono 16 kHz analysis audio")

        step_sec = chunk_duration_sec - overlap_sec
        if step_sec <= 0:
            raise AudioProcessingError("Audio chunk overlap must be shorter than chunk duration")
        start_sec = 0.0
        chunk_index = 1
        while start_sec < duration:
            end_sec = min(duration, start_sec + chunk_duration_sec)
            start_frame = min(frame_count, int(round(start_sec * sample_rate)))
            end_frame = min(frame_count, int(round(end_sec * sample_rate)))
            source.setpos(start_frame)
            frames = source.readframes(max(0, end_frame - start_frame))
            filename = f"audio_chunk_{chunk_index:03d}.wav"
            output = output_dir / filename
            with wave.open(str(output), "wb") as chunk_file:
                chunk_file.setnchannels(channels)
                chunk_file.setsampwidth(sample_width)
                chunk_file.setframerate(sample_rate)
                chunk_file.writeframes(frames)
            chunks.append({
                "chunk_id": f"AUD{chunk_index:03d}",
                "file_name": filename,
                "sha256": sha256_file(output),
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "duration_sec": round(end_sec - start_sec, 3),
                "sample_rate_hz": sample_rate,
                "channels": channels,
                "timestamp_semantics": "source_video_timeline",
            })
            if end_sec >= duration:
                break
            start_sec = round(start_sec + step_sec, 3)
            chunk_index += 1
    return chunks


def prepare_audio(
    video_path: Path,
    job_id: str,
    *,
    audio_stream: dict[str, Any] | None,
    duration_sec: float,
) -> tuple[dict[str, Any], list[str]]:
    """Extract a mono 16 kHz analysis track, create overlapped chunks and measure basic signal stats."""
    if not audio_stream:
        return ({
            "available": False,
            "transcription_status": "skipped_no_audio",
            "chunks": [],
            "transcript_segments": [],
        }, ["No audio stream was found in the uploaded video."])

    if not shutil.which(settings.ffmpeg_bin):
        raise AudioProcessingError(f"ffmpeg executable not found: {settings.ffmpeg_bin}")

    audio_dir = settings.jobs_dir / job_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    temp_wav = audio_dir / ".analysis_audio.tmp.wav"
    stream_index = int(audio_stream["index"])
    timeout = max(300, int(duration_sec * 2) + 120)

    source_audio_path = audio_dir / "audio_source.flac"
    command = [
        settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        # Lossless reference track retains the source channel count and sample rate.
        "-map", f"0:{stream_index}", "-vn", "-c:a", "flac", "-compression_level", "5",
        str(source_audio_path),
        # Separate mono 16 kHz working copy is for ASR and signal measurements only.
        "-map", f"0:{stream_index}", "-vn", "-ac", "1",
        "-ar", str(settings.audio_analysis_sample_rate_hz), "-c:a", "pcm_s16le",
        str(temp_wav),
    ]
    try:
        _run(command, timeout=timeout)
        if not temp_wav.is_file() or temp_wav.stat().st_size < 44:
            raise AudioProcessingError("Extracted audio track is empty or invalid")
        with wave.open(str(temp_wav), "rb") as source:
            actual_duration = source.getnframes() / float(source.getframerate())
        metrics = _audio_signal_stats(temp_wav, timeout=timeout)
        chunks = _write_chunks(
            temp_wav,
            audio_dir,
            chunk_duration_sec=settings.audio_chunk_duration_sec,
            overlap_sec=settings.audio_chunk_overlap_sec,
        )
    finally:
        temp_wav.unlink(missing_ok=True)

    manifest: dict[str, Any] = {
        "available": True,
        "stream_index": stream_index,
        "source_codec": audio_stream.get("codec_name"),
        "source_sample_rate_hz": audio_stream.get("sample_rate"),
        "source_channels": audio_stream.get("channels"),
        "source_audio_file_name": source_audio_path.name,
        "source_audio_sha256": sha256_file(source_audio_path),
        "source_audio_size_bytes": source_audio_path.stat().st_size,
        "analysis_sample_rate_hz": settings.audio_analysis_sample_rate_hz,
        "analysis_channels": 1,
        "analysis_format": "pcm_s16le_wav",
        "duration_sec": round(actual_duration, 3),
        "chunk_duration_sec": settings.audio_chunk_duration_sec,
        "chunk_overlap_sec": settings.audio_chunk_overlap_sec,
        "chunks": chunks,
        "signal_metrics": metrics,
        "transcription_status": "not_configured",
        "transcription_model": None,
        "transcript_segments": [],
    }

    warnings: list[str] = []
    if abs(actual_duration - duration_sec) > 1.0:
        warnings.append(
            f"Audio duration ({actual_duration:.3f}s) differs from container duration ({duration_sec:.3f}s) by more than 1s."
        )
    if not settings.audio_transcription_enabled:
        warnings.append(
            "Audio was extracted and segmented, but ASR is not configured. Set AUDIO_TRANSCRIPTION_BASE_URL and AUDIO_TRANSCRIPTION_MODEL to enable timestamped transcription."
        )
        return manifest, warnings

    from .providers.openai_transcription import TranscriptionError, transcribe_audio_file

    transcript_segments: list[dict[str, Any]] = []
    failed_chunks: list[str] = []
    for chunk in chunks:
        try:
            response = transcribe_audio_file(
                audio_dir / chunk["file_name"],
                language=settings.audio_transcription_language or None,
            )
        except TranscriptionError as exc:
            failed_chunks.append(chunk["chunk_id"])
            warnings.append(f"ASR failed for {chunk['chunk_id']}: {exc}")
            continue

        response_segments = response.get("segments")
        if isinstance(response_segments, list) and response_segments:
            for item in response_segments:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    continue
                try:
                    local_start = max(0.0, float(item.get("start", 0)))
                    local_end = max(local_start, float(item.get("end", local_start)))
                except (TypeError, ValueError):
                    continue
                transcript_segments.append({
                    "transcript_id": f"T{len(transcript_segments) + 1:05d}",
                    "start_sec": round(chunk["start_sec"] + local_start, 3),
                    "end_sec": round(min(chunk["end_sec"], chunk["start_sec"] + local_end), 3),
                    "text": item["text"].strip()[:2000],
                    "source_chunk_id": chunk["chunk_id"],
                    "timestamp_precision": "asr_segment",
                })
        elif isinstance(response.get("text"), str) and response["text"].strip():
            transcript_segments.append({
                "transcript_id": f"T{len(transcript_segments) + 1:05d}",
                "start_sec": chunk["start_sec"],
                "end_sec": chunk["end_sec"],
                "text": response["text"].strip()[:4000],
                "source_chunk_id": chunk["chunk_id"],
                "timestamp_precision": "chunk_window",
            })

    # Adjacent chunks overlap by design. Drop near-identical duplicate text in overlapping time windows.
    deduped: list[dict[str, Any]] = []
    for segment in sorted(transcript_segments, key=lambda x: (x["start_sec"], x["end_sec"])):
        normal_text = re.sub(r"\s+", "", segment["text"])
        duplicate = any(
            re.sub(r"\s+", "", prior["text"]) == normal_text
            and segment["start_sec"] <= prior["end_sec"]
            for prior in deduped[-8:]
        )
        if normal_text and not duplicate:
            segment["transcript_id"] = f"T{len(deduped) + 1:05d}"
            deduped.append(segment)

    manifest["transcript_segments"] = deduped
    manifest["transcription_model"] = settings.audio_transcription_model
    manifest["transcription_status"] = (
        "failed" if failed_chunks and not deduped
        else "partial" if failed_chunks
        else "completed"
    )
    manifest["failed_chunk_ids"] = failed_chunks
    if failed_chunks:
        warnings.append(f"ASR did not complete for {len(failed_chunks)} audio chunk(s).")
    return manifest, warnings
