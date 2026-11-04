from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load local development settings before constructing the immutable Settings object.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Cockpit Benchmark Analyzer")
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data")).resolve()
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "2048"))
    max_video_duration_sec: int = int(os.getenv("MAX_VIDEO_DURATION_SEC", "7200"))
    sample_interval_sec: int = int(os.getenv("SAMPLE_INTERVAL_SEC", "5"))
    max_frames: int = int(os.getenv("MAX_FRAMES", "120"))
    sampling_policy: str = os.getenv("SAMPLING_POLICY", "uniform_v1").strip().lower()
    scene_change_threshold: float = float(os.getenv("SCENE_CHANGE_THRESHOLD", "0.30"))
    scene_detection_timeout_sec: int = int(os.getenv("SCENE_DETECTION_TIMEOUT_SEC", "180"))
    ffmpeg_bin: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin: str = os.getenv("FFPROBE_BIN", "ffprobe")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "").strip()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    vlm_model: str = os.getenv("VLM_MODEL", "").strip()
    vlm_timeout_sec: int = int(os.getenv("VLM_TIMEOUT_SEC", "180"))
    audio_analysis_sample_rate_hz: int = int(os.getenv("AUDIO_ANALYSIS_SAMPLE_RATE_HZ", "16000"))
    audio_chunk_duration_sec: int = int(os.getenv("AUDIO_CHUNK_DURATION_SEC", "60"))
    audio_chunk_overlap_sec: float = float(os.getenv("AUDIO_CHUNK_OVERLAP_SEC", "1"))
    audio_transcription_base_url: str = os.getenv("AUDIO_TRANSCRIPTION_BASE_URL", "").strip()
    audio_transcription_api_key: str = (
        os.getenv("AUDIO_TRANSCRIPTION_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    audio_transcription_model: str = os.getenv("AUDIO_TRANSCRIPTION_MODEL", "").strip()
    audio_transcription_language: str = os.getenv("AUDIO_TRANSCRIPTION_LANGUAGE", "zh").strip()
    audio_transcription_timeout_sec: int = int(os.getenv("AUDIO_TRANSCRIPTION_TIMEOUT_SEC", "180"))

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def provider_enabled(self) -> bool:
        return bool(self.openai_base_url and self.vlm_model)

    @property
    def audio_transcription_enabled(self) -> bool:
        return bool(self.audio_transcription_base_url and self.audio_transcription_model)

    @property
    def require_human_review(self) -> bool:
        return os.getenv("REQUIRE_HUMAN_REVIEW", "true").lower() not in {"0", "false", "no"}

    def ensure_dirs(self) -> None:
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
