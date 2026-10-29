from __future__ import annotations

from app.pipeline import _normalise_model_output, load_rubric
from app.video import sample_timestamps


def _frame(evidence_id: str):
    return {"evidence_id": evidence_id, "timestamp_sec": 0.0, "absolute_path": "/tmp/not-used.jpg"}


def test_sample_timestamps_stops_at_frame_cap():
    assert sample_timestamps(100, 5, 4) == [0.0, 30.0, 65.0, 95.0]


def test_sample_timestamps_short_clip_has_one_sample():
    assert sample_timestamps(0.8, 5, 12) == [0.0]


def test_rubric_weights_sum_to_one_and_has_three_metrics():
    rubric = load_rubric()
    assert len(rubric["metrics"]) == 3
    assert round(sum(m["weight"] for m in rubric["metrics"]), 6) == 1.0


def test_normaliser_fills_missing_metrics_and_downgrades_unknown_evidence():
    rubric = load_rubric()
    raw = {
        "observations": [{"evidence_id": "F999", "observation": "not real evidence", "confidence": 0.9}],
        "scores": [
            {"metric_id": "ui_legibility", "score": 5, "status": "scored", "rationale": "looks great", "evidence_ids": ["F999"]}
        ],
    }
    observations, scores, warnings = _normalise_model_output(raw, frames=[_frame("F001")], rubric=rubric)
    assert observations == []
    assert len(scores) == 3
    assert scores[0].score is None
    assert scores[0].status == "evidence_insufficient"
    assert scores[0].evidence_ids == []
    assert len(warnings) >= 2


def test_normaliser_keeps_score_only_with_valid_evidence_and_reason():
    rubric = load_rubric()
    raw = {
        "observations": [{"evidence_id": "F001", "observation": "可见导航结果列表", "confidence": 0.8}],
        "scores": [
            {"metric_id": "ui_legibility", "score": 4, "status": "scored", "rationale": "关键文字可辨识", "evidence_ids": ["F001"]}
        ],
    }
    observations, scores, warnings = _normalise_model_output(raw, frames=[_frame("F001")], rubric=rubric)
    assert len(observations) == 1
    assert scores[0].score == 4
    assert scores[0].status == "scored"
    assert scores[0].evidence_ids == ["F001"]
    assert scores[1].score is None
    assert warnings == []
