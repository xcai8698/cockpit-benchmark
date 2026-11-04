from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import settings


class TranscriptionError(RuntimeError):
    pass


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/audio/transcriptions"):
        return value
    return value + "/audio/transcriptions"


def _multipart_body(path: Path, *, language: str | None) -> tuple[bytes, str]:
    boundary = "----CockpitBenchmark" + uuid.uuid4().hex
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )

    field("model", settings.audio_transcription_model)
    field("response_format", "verbose_json")
    field("timestamp_granularities[]", "segment")
    if language:
        field("language", language)

    filename = path.name.replace('"', "_")
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n".encode("utf-8")
        + path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), boundary


def transcribe_audio_file(path: Path, *, language: str | None = None) -> dict[str, Any]:
    if not settings.audio_transcription_enabled:
        raise TranscriptionError("Audio transcription is not configured")
    body, boundary = _multipart_body(path, language=language)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if settings.audio_transcription_api_key:
        headers["Authorization"] = f"Bearer {settings.audio_transcription_api_key}"
    request = urllib.request.Request(
        _endpoint(settings.audio_transcription_base_url),
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.audio_transcription_timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise TranscriptionError(f"ASR provider HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TranscriptionError(f"ASR provider request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise TranscriptionError("ASR provider returned a non-object response")
    return payload
