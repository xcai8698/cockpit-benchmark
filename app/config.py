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
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "500"))
    sample_interval_sec: int = int(os.getenv("SAMPLE_INTERVAL_SEC", "5"))
    max_frames: int = int(os.getenv("MAX_FRAMES", "12"))
    sampling_policy: str = os.getenv("SAMPLING_POLICY", "uniform_v1").strip().lower()
    scene_change_threshold: float = float(os.getenv("SCENE_CHANGE_THRESHOLD", "0.30"))
    scene_detection_timeout_sec: int = int(os.getenv("SCENE_DETECTION_TIMEOUT_SEC", "180"))
    ffmpeg_bin: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin: str = os.getenv("FFPROBE_BIN", "ffprobe")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "").strip()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    vlm_model: str = os.getenv("VLM_MODEL", "").strip()
    vlm_timeout_sec: int = int(os.getenv("VLM_TIMEOUT_SEC", "180"))
    require_human_review: bool = os.getenv("REQUIRE_HUMAN_REVIEW", "true").lower() not in {"0", "false", "no"}

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def provider_enabled(self) -> bool:
        return bool(self.openai_base_url and self.vlm_model)

    def ensure_dirs(self) -> None:
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
