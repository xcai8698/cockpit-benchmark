from types import SimpleNamespace

from app.models import AVTimelineEvent
from app.pipeline import _build_av_timeline


def test_av_timeline_aligns_visual_transcript_and_silence_evidence():
    frames = [
        SimpleNamespace(evidence_id="F001", timestamp_sec=12.0),
        SimpleNamespace(evidence_id="F002", timestamp_sec=25.0),
    ]
    audio_manifest = {
        "chunks": [
            {"chunk_id": "AUD001", "start_sec": 0.0, "end_sec": 60.0},
        ],
        "transcript_segments": [
            {
                "transcript_id": "T00001",
                "start_sec": 11.2,
                "end_sec": 13.4,
                "text": "前方路口请左转",
                "source_chunk_id": "AUD001",
                "timestamp_precision": "asr_segment",
            }
        ],
        "signal_metrics": {
            "silence_intervals": [
                {"start_sec": 18.0, "end_sec": 19.2, "duration_sec": 1.2}
            ]
        },
    }

    events = _build_av_timeline(frames, audio_manifest)

    assert [event["event_type"] for event in events] == [
        "visual_frame", "speech_transcript", "audio_silence", "visual_frame"
    ]
    assert events[1]["start_sec"] == 11.2
    assert events[1]["evidence_refs"] == ["T00001", "AUD001"]
    assert events[2]["evidence_refs"] == ["AUD001"]
    assert [event["event_id"] for event in events] == [
        "EV00001", "EV00002", "EV00003", "EV00004"
    ]
    for event in events:
        AVTimelineEvent(**event)
