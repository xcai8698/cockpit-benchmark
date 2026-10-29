from pathlib import Path

import pytest

from app import video
from app.models import SamplingManifest


def test_uniform_sampler_keeps_legacy_short_video_grid():
    assert video.sample_timestamps(40, 5, 12) == [
        0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0
    ]


def test_uniform_sampler_spreads_frames_across_long_video():
    timestamps = video.sample_timestamps(180, 5, 12)

    assert len(timestamps) == 12
    assert timestamps[0] == 0.0
    assert timestamps[-1] == 175.0
    assert timestamps == sorted(set(timestamps))


@pytest.mark.parametrize(
    ("duration_sec", "interval_sec", "max_frames"),
    [(0, 5, 12), (10, 0, 12), (10, 5, 0), (float("inf"), 5, 12)],
)
def test_sampler_rejects_invalid_limits(duration_sec, interval_sec, max_frames):
    with pytest.raises(ValueError):
        video.sample_timestamps(duration_sec, interval_sec, max_frames)


def test_manual_supplemental_timestamps_are_included_and_audited():
    plan = video.plan_sampling(
        60,
        5,
        8,
        policy_id="uniform_v1",
        supplemental_timestamps=[12.5, 42, 42, 60, -1],
    )

    assert 12.5 in plan.timestamps
    assert 42.0 in plan.timestamps
    assert len(plan.timestamps) <= 8
    assert plan.manifest["supplemental_timestamps_used_sec"] == [12.5, 42.0]
    assert plan.manifest["supplemental_timestamps_dropped_sec"] == []
    assert any("outside the video duration" in warning for warning in plan.warnings)
    SamplingManifest(**plan.manifest)


def test_manual_supplemental_timestamps_respect_frame_budget():
    requested = [float(i) for i in range(1, 14)]
    plan = video.plan_sampling(
        100,
        5,
        4,
        policy_id="uniform_v1",
        supplemental_timestamps=requested,
    )

    assert plan.timestamps == [1.0, 5.0, 9.0, 13.0]
    assert plan.manifest["supplemental_timestamps_used_sec"] == [1.0, 5.0, 9.0, 13.0]
    assert len(plan.manifest["supplemental_timestamps_dropped_sec"]) == 9
    assert len(plan.timestamps) == 4


def test_scene_aware_policy_includes_scene_and_manual_candidates(monkeypatch):
    monkeypatch.setattr(video, "detect_scene_changes", lambda *_args, **_kwargs: [17.3, 31.1])

    plan = video.build_sampling_plan(
        Path("synthetic.mp4"),
        60,
        5,
        8,
        policy_id="scene_aware_v1",
        supplemental_timestamps=[12.5],
    )

    assert 12.5 in plan.timestamps
    assert 17.3 in plan.timestamps
    assert 31.1 in plan.timestamps
    assert len(plan.timestamps) <= 8
    assert plan.manifest["scene_detection_attempted"] is True
    assert plan.manifest["scene_detection_succeeded"] is True
    assert plan.manifest["scene_change_timestamps_used_sec"] == [17.3, 31.1]
    SamplingManifest(**plan.manifest)


def test_scene_detection_failure_falls_back_without_failing_analysis(monkeypatch):
    def fail_detection(*_args, **_kwargs):
        raise video.VideoProcessingError("synthetic timeout")

    monkeypatch.setattr(video, "detect_scene_changes", fail_detection)
    plan = video.build_sampling_plan(
        Path("synthetic.mp4"), 60, 5, 8, policy_id="scene_aware_v1"
    )

    assert plan.timestamps
    assert len(plan.timestamps) <= 8
    assert plan.manifest["scene_detection_attempted"] is True
    assert plan.manifest["scene_detection_succeeded"] is False
    assert any("fell back to temporal coverage" in warning for warning in plan.warnings)


def test_coverage_gap_manifest_is_deterministic():
    first = video.plan_sampling(180, 5, 12, policy_id="scene_aware_v1", scene_change_timestamps=[33, 79])
    second = video.plan_sampling(180, 5, 12, policy_id="scene_aware_v1", scene_change_timestamps=[33, 79])

    assert first.timestamps == second.timestamps
    assert first.manifest == second.manifest
    assert first.manifest["max_gap_sec"] >= 0
    assert isinstance(first.manifest["coverage_gaps"], list)
