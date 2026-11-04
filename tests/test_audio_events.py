from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from app.providers import openai_audio_events


def test_normalise_audio_events_offsets_chunk_time_and_validates_fields():
    events = openai_audio_events._normalise_events(
        [
            {
                "event_type": "alert_tone",
                "start_sec": 1.25,
                "end_sec": 2.5,
                "description": "Short warning chime",
                "confidence": 0.9,
            },
            {
                "event_type": "made_up",
                "start_sec": -1,
                "end_sec": 2,
                "description": "Unknown event",
                "confidence": 4,
            },
            {"event_type": "music", "start_sec": "bad", "end_sec": 3, "description": "bad"},
            {"event_type": "music", "start_sec": 4, "end_sec": 4, "description": "zero duration"},
        ],
        chunk_id="AUD002",
        chunk_start_sec=60.0,
        chunk_duration_sec=60.0,
    )

    assert len(events) == 2
    assert events[0]["event_type"] == "alert_tone"
    assert events[0]["start_sec"] == 61.25
    assert events[0]["end_sec"] == 62.5
    assert events[0]["source_chunk_id"] == "AUD002"
    assert events[0]["timestamp_precision"] == "model_estimate"
    assert events[1]["event_type"] == "other"
    assert events[1]["start_sec"] == 60.0
    assert events[1]["end_sec"] == 62.0
    assert events[1]["confidence"] is None


def test_parse_audio_event_json_accepts_json_embedded_in_text():
    parsed = openai_audio_events._parse_event_json(
        'Audio analysis:\n{"events":[{"event_type":"music"}]}\nDone'
    )
    assert parsed["events"][0]["event_type"] == "music"


def test_audio_event_request_sends_audio_input_and_returns_source_timestamps(tmp_path, monkeypatch):
    audio_path = tmp_path / "audio_chunk_002.wav"
    audio_bytes = b"RIFF\x24\x00\x00\x00WAVE-test-audio"
    audio_path.write_bytes(audio_bytes)
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "events": [{
                                "event_type": "turn_signal_click",
                                "start_sec": 5.0,
                                "end_sec": 7.0,
                                "description": "Repeated turn signal clicks",
                                "confidence": 0.75,
                            }]
                        })
                    }
                }]
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(openai_audio_events.urllib.request, "urlopen", fake_urlopen)
    events = openai_audio_events.analyze_audio_chunk(
        audio_path,
        base_url="http://localhost:1234/v1",
        api_key="test-key",
        model="audio-test-model",
        timeout_sec=45,
        chunk_id="AUD002",
        chunk_start_sec=60.0,
        chunk_duration_sec=60.0,
    )

    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["timeout"] == 45
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    content = captured["payload"]["messages"][0]["content"]
    audio_part = next(item for item in content if item["type"] == "input_audio")
    assert audio_part["input_audio"]["format"] == "wav"
    assert base64.b64decode(audio_part["input_audio"]["data"]) == audio_bytes
    assert events[0]["start_sec"] == 65.0
    assert events[0]["end_sec"] == 67.0
    assert events[0]["source_chunk_id"] == "AUD002"


def test_audio_event_is_linked_into_the_source_time_av_timeline():
    from app.pipeline import _build_av_timeline

    timeline = _build_av_timeline(
        [],
        {
            "chunks": [{
                "chunk_id": "AUD002",
                "start_sec": 60.0,
                "end_sec": 120.0,
            }],
            "transcript_segments": [],
            "audio_events": [{
                "audio_event_id": "AE00001",
                "event_type": "alert_tone",
                "start_sec": 65.0,
                "end_sec": 66.2,
                "description": "Short warning chime",
                "confidence": 0.8,
                "source_chunk_id": "AUD002",
                "timestamp_precision": "model_estimate",
            }],
            "signal_metrics": {},
        },
    )

    assert len(timeline) == 1
    assert timeline[0]["event_type"] == "audio_event"
    assert timeline[0]["modality"] == "audio"
    assert timeline[0]["start_sec"] == 65.0
    assert timeline[0]["evidence_refs"] == ["AE00001", "AUD002"]
    assert timeline[0]["timestamp_precision"] == "model_estimate"
