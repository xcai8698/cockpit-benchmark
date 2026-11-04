from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

from app import audio
from app.models import AudioManifest
from app.providers import openai_transcription


def _make_wav(path: Path, *, seconds: int = 5, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * seconds * sample_rate)


def test_audio_chunking_preserves_timeline_and_overlap(tmp_path):
    source = tmp_path / "source.wav"
    _make_wav(source, seconds=5)

    chunks = audio._write_chunks(
        source,
        tmp_path,
        chunk_duration_sec=3,
        overlap_sec=1,
    )

    assert len(chunks) == 2
    assert [(item["start_sec"], item["end_sec"]) for item in chunks] == [(0.0, 3.0), (2.0, 5.0)]
    assert all(item["timestamp_semantics"] == "source_video_timeline" for item in chunks)
    assert all(Path(tmp_path / item["file_name"]).exists() for item in chunks)


def test_prepare_audio_skips_cleanly_when_video_has_no_audio(tmp_path):
    manifest, warnings = audio.prepare_audio(
        tmp_path / "silent.mp4",
        "testjob",
        audio_stream=None,
        duration_sec=30,
    )

    assert manifest["available"] is False
    assert manifest["transcription_status"] == "skipped_no_audio"
    assert manifest["chunks"] == []
    assert warnings


def test_prepare_audio_extracts_chunks_without_transcription(tmp_path, monkeypatch):
    fake_settings = SimpleNamespace(
        ffmpeg_bin="ffmpeg",
        jobs_dir=tmp_path / "jobs",
        audio_analysis_sample_rate_hz=16000,
        audio_chunk_duration_sec=3,
        audio_chunk_overlap_sec=1,
        audio_transcription_enabled=False,
    )
    monkeypatch.setattr(audio, "settings", fake_settings)
    monkeypatch.setattr(audio.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(command, *, timeout):
        for value in command:
            item = str(value)
            if item.endswith("audio_source.flac"):
                Path(item).write_bytes(b"fLaC-test-audio")
            elif item.endswith(".analysis_audio.tmp.wav"):
                _make_wav(Path(item), seconds=5)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(audio, "_run", fake_run)
    monkeypatch.setattr(
        audio,
        "_audio_signal_stats",
        lambda *_args, **_kwargs: {"peak_dbfs": -1.0, "rms_dbfs": -20.0, "silence_interval_count": 0},
    )

    manifest, warnings = audio.prepare_audio(
        tmp_path / "source.mp4",
        "testjob",
        audio_stream={"index": 1, "codec_name": "aac", "sample_rate": 48000, "channels": 2},
        duration_sec=5,
    )

    assert manifest["available"] is True
    assert manifest["analysis_sample_rate_hz"] == 16000
    assert manifest["source_audio_file_name"] == "audio_source.flac"
    assert manifest["source_audio_sha256"]
    assert manifest["source_audio_size_bytes"] > 0
    assert len(manifest["chunks"]) == 2
    assert manifest["chunks"][1]["start_sec"] == 2.0
    assert manifest["transcription_status"] == "not_configured"
    AudioManifest(**manifest)
    assert any("ASR is not configured" in warning for warning in warnings)
    assert not (fake_settings.jobs_dir / "testjob" / "audio" / ".analysis_audio.tmp.wav").exists()


def test_transcription_multipart_contains_model_and_timestamp_request(tmp_path, monkeypatch):
    sample = tmp_path / "audio_chunk_001.wav"
    sample.write_bytes(b"RIFF-test-audio")
    monkeypatch.setattr(
        openai_transcription,
        "settings",
        SimpleNamespace(audio_transcription_model="whisper-1"),
    )

    body, boundary = openai_transcription._multipart_body(sample, language="zh")

    assert f"boundary={boundary}"
    assert b'name="model"' in body
    assert b"whisper-1" in body
    assert b'name="timestamp_granularities[]"' in body
    assert b"segment" in body
    assert b'name="language"' in body
    assert b"audio_chunk_001.wav" in body
    assert b"RIFF-test-audio" in body


def test_audio_manifest_accepts_timestamped_sound_event_evidence():
    manifest = AudioManifest(
        available=True,
        transcription_status="not_configured",
        event_analysis_status="completed",
        event_analysis_model="gpt-audio",
        event_analysis_chunks=["AUD001"],
        chunks=[{
            "chunk_id": "AUD001",
            "file_name": "audio_chunk_001.wav",
            "sha256": "abc123",
            "start_sec": 0,
            "end_sec": 60,
            "duration_sec": 60,
            "sample_rate_hz": 16000,
            "channels": 1,
            "timestamp_semantics": "source_video_timeline",
        }],
        audio_events=[{
            "audio_event_id": "AE00001",
            "event_type": "alert_tone",
            "start_sec": 12.1,
            "end_sec": 12.8,
            "description": "Short warning chime",
            "confidence": 0.85,
            "source_chunk_id": "AUD001",
            "timestamp_precision": "model_estimate",
        }],
    )

    assert manifest.event_analysis_status == "completed"
    assert manifest.audio_events[0].source_chunk_id == "AUD001"


def test_prepare_audio_runs_sound_event_model_when_configured(tmp_path, monkeypatch):
    fake_settings = SimpleNamespace(
        ffmpeg_bin="ffmpeg",
        jobs_dir=tmp_path / "jobs",
        audio_analysis_sample_rate_hz=16000,
        audio_chunk_duration_sec=3,
        audio_chunk_overlap_sec=1,
        audio_transcription_enabled=False,
        audio_event_analysis_enabled=True,
        audio_event_model="audio-test-model",
        audio_event_base_url="http://localhost/v1",
        audio_event_api_key="test-key",
        audio_event_timeout_sec=30,
        audio_event_max_chunks=40,
    )
    monkeypatch.setattr(audio, "settings", fake_settings)
    monkeypatch.setattr(audio.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(command, *, timeout):
        for value in command:
            item = str(value)
            if item.endswith("audio_source.flac"):
                Path(item).write_bytes(b"fLaC-test-audio")
            elif item.endswith(".analysis_audio.tmp.wav"):
                _make_wav(Path(item), seconds=5)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(audio, "_run", fake_run)
    monkeypatch.setattr(
        audio,
        "_audio_signal_stats",
        lambda *_args, **_kwargs: {"peak_dbfs": -1.0, "rms_dbfs": -20.0, "silence_interval_count": 0},
    )
    from app.providers import openai_audio_events

    calls = []

    def fake_analyze(path, **kwargs):
        calls.append((path.name, kwargs["chunk_id"]))
        return [{
            "event_type": "alert_tone",
            "start_sec": kwargs["chunk_start_sec"] + 0.25,
            "end_sec": kwargs["chunk_start_sec"] + 0.75,
            "description": "Short warning chime",
            "confidence": 0.9,
            "source_chunk_id": kwargs["chunk_id"],
            "timestamp_precision": "model_estimate",
        }]

    monkeypatch.setattr(openai_audio_events, "analyze_audio_chunk", fake_analyze)
    manifest, warnings = audio.prepare_audio(
        tmp_path / "source.mp4",
        "event-job",
        audio_stream={"index": 1, "codec_name": "aac", "sample_rate": 48000, "channels": 2},
        duration_sec=5,
    )

    assert len(calls) == 2
    assert manifest["event_analysis_status"] == "completed"
    assert manifest["event_analysis_model"] == "audio-test-model"
    assert len(manifest["audio_events"]) == 2
    assert manifest["audio_events"][0]["audio_event_id"] == "AE00001"
    AudioManifest(**manifest)
    assert any("ASR is not configured" in warning for warning in warnings)
