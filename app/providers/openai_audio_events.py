from __future__ import annotations

import base64
import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class AudioEventAnalysisError(RuntimeError):
    pass


EVENT_TYPES = {
    "speech", "navigation_prompt", "voice_assistant", "alert_tone",
    "turn_signal_click", "button_feedback", "music", "cabin_noise", "other",
}


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value if value.endswith("/chat/completions") else value + "/chat/completions"


def _message_text(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AudioEventAnalysisError("Audio event provider returned no message content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "\n".join(fragments)
    raise AudioEventAnalysisError("Audio event provider returned unsupported message content")


def _parse_event_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise AudioEventAnalysisError("Audio event provider did not return a JSON object")
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise AudioEventAnalysisError("Audio event provider returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AudioEventAnalysisError("Audio event response must be a JSON object")
    return value


def _normalise_events(
    raw_events: Any,
    *,
    chunk_id: str,
    chunk_start_sec: float,
    chunk_duration_sec: float,
) -> list[dict[str, Any]]:
    if not isinstance(raw_events, list):
        raise AudioEventAnalysisError("Audio event response must contain an events array")

    normalised: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        try:
            local_start = float(item.get("start_sec"))
            local_end = float(item.get("end_sec"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(local_start) or not math.isfinite(local_end):
            continue
        start = max(0.0, min(chunk_duration_sec, local_start))
        end = max(0.0, min(chunk_duration_sec, local_end))
        if end <= start:
            continue
        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            continue
        event_type = item.get("event_type")
        if event_type not in EVENT_TYPES:
            event_type = "other"
        confidence = item.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        if confidence_value is not None and (
            not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0
        ):
            confidence_value = None

        normalised.append({
            "event_type": event_type,
            "start_sec": round(chunk_start_sec + start, 3),
            "end_sec": round(chunk_start_sec + end, 3),
            "description": description.strip()[:1000],
            "confidence": confidence_value,
            "source_chunk_id": chunk_id,
            "timestamp_precision": "model_estimate",
        })
    return sorted(normalised, key=lambda event: (event["start_sec"], event["end_sec"]))


def analyze_audio_chunk(
    path: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_sec: int,
    chunk_id: str,
    chunk_start_sec: float,
    chunk_duration_sec: float,
) -> list[dict[str, Any]]:
    """Request timestamped sound events from an audio-capable Chat Completions model.

    This is a specialist audio-only pass, not audiovisual reasoning. A later fusion
    step must compare these events with independently grounded visual observations.
    """
    if not path.is_file():
        raise AudioEventAnalysisError(f"Audio chunk not found: {path.name}")
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise AudioEventAnalysisError(f"Could not read audio chunk {path.name}: {exc}") from exc

    prompt = (
        f"Analyze the supplied audio clip. Its duration is {chunk_duration_sec:.3f} seconds. "
        "Return only a JSON object with an 'events' array. Report only clearly audible events; "
        "do not infer what may be happening visually. Use local timestamps relative to the start "
        "of this audio clip, with start_sec and end_sec in seconds. Event types must be one of: "
        "speech, navigation_prompt, voice_assistant, alert_tone, turn_signal_click, "
        "button_feedback, music, cabin_noise, other. Give concise evidence-grounded descriptions "
        "and confidence from 0 to 1 when possible. Do not transcribe full speech; speech text is "
        "handled by ASR separately. Do not invent events to fill gaps. Output schema: "
        '{"events":[{"event_type":"alert_tone","start_sec":1.2,"end_sec":1.8,'
        '"description":"A short high-pitched alert chime","confidence":0.8}]}'
    )
    request_payload = {
        "model": model,
        "modalities": ["text"],
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}},
            ],
        }],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        _endpoint(base_url),
        data=json.dumps(request_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise AudioEventAnalysisError(f"Audio event provider HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AudioEventAnalysisError(f"Audio event provider request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise AudioEventAnalysisError("Audio event provider returned a non-object response")
    parsed = _parse_event_json(_message_text(payload))
    return _normalise_events(
        parsed.get("events"),
        chunk_id=chunk_id,
        chunk_start_sec=chunk_start_sec,
        chunk_duration_sec=chunk_duration_sec,
    )
