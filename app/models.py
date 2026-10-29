from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


JobStatus = Literal["queued", "processing", "completed", "completed_unscored", "failed"]
ScoreStatus = Literal["scored", "evidence_insufficient"]


class VideoMetadata(BaseModel):
    original_filename: str
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    model_year: str | None = None
    software_version: str | None = None
    scenario: str | None = None
    source_url: str | None = None


class EvidenceFrame(BaseModel):
    evidence_id: str
    timestamp_sec: float = Field(ge=0)
    timestamp_semantics: Literal["ffmpeg_seek_target"] = "ffmpeg_seek_target"
    file_name: str
    sha256: str
    mime_type: Literal["image/jpeg"] = "image/jpeg"
    width: int | None = None
    height: int | None = None
    source_video: str


class CoverageGap(BaseModel):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(ge=0)
    duration_sec: float = Field(ge=0)


class SamplingManifest(BaseModel):
    policy_id: str
    policy_version: str
    interval_sec: int = Field(gt=0)
    max_frames: int = Field(gt=0)
    scene_detection_attempted: bool = False
    scene_detection_succeeded: bool = False
    scene_threshold: float | None = Field(default=None, gt=0, lt=1)
    scene_change_candidates_sec: list[float] = Field(default_factory=list)
    scene_change_timestamps_used_sec: list[float] = Field(default_factory=list)
    supplemental_timestamps_requested_sec: list[float] = Field(default_factory=list)
    supplemental_timestamps_used_sec: list[float] = Field(default_factory=list)
    supplemental_timestamps_dropped_sec: list[float] = Field(default_factory=list)
    candidate_count: int = Field(ge=0)
    selected_timestamps_sec: list[float] = Field(default_factory=list)
    max_gap_sec: float = Field(ge=0)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)


class Observation(BaseModel):
    evidence_id: str
    observation: str = Field(min_length=1, max_length=1200)
    confidence: float | None = Field(default=None, ge=0, le=1)


class MetricScore(BaseModel):
    metric_id: str
    score: int | None = Field(default=None, ge=1, le=5)
    status: ScoreStatus
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    weight: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def score_requires_evidence(self):
        if self.score is not None and (self.status != "scored" or not self.evidence_ids):
            raise ValueError("A scored metric must have status='scored' and at least one evidence ID")
        if self.score is None and self.status != "evidence_insufficient":
            raise ValueError("A null score must have status='evidence_insufficient'")
        return self


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    analysis_id: str
    created_at: str
    mode: Literal["openai_compatible_vlm", "no_model"]
    model_name: str | None = None
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    reviewer: str | None = None
    reviewed_at: str | None = None
    review_notes: str | None = None
    review_history: list[dict[str, str | None]] = Field(default_factory=list)
    rubric_id: str
    rubric_version: str
    video_metadata: VideoMetadata
    duration_sec: float
    sampled_frames: list[EvidenceFrame]
    sampling_manifest: SamplingManifest | None = None
    observations: list[Observation] = Field(default_factory=list)
    scores: list[MetricScore]
    overall_score_100: float | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance_note: str = (
        "Automatic results are provisional. Human review is required before publication or ranking."
    )

    @field_validator("scores")
    @classmethod
    def unique_metric_scores(cls, values: list[MetricScore]):
        ids = [v.metric_id for v in values]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate metric_id in scores")
        return values
