from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import settings


class ProviderError(RuntimeError):
    pass


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return value + "/chat/completions"


def _image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _response_text(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("Provider response did not contain choices[0].message.content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text"]
        if chunks:
            return "\n".join(chunks)
    raise ProviderError("Provider response content was not readable text")


def analyze_frames(*, frames: list[dict[str, Any]], rubric: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if not settings.provider_enabled:
        raise ProviderError("OPENAI_BASE_URL and VLM_MODEL must be set to enable VLM analysis")

    metrics = []
    for metric in rubric["metrics"]:
        metrics.append({
            "metric_id": metric["metric_id"],
            "name": metric["name"],
            "definition": metric["definition"],
            "weight": metric["weight"],
            "anchors": metric["anchors"],
        })

    instructions = {
        "task": "Analyze only visible cockpit interface evidence in the supplied sampled frames.",
        "vehicle_metadata_is_unverified_context": metadata,
        "rubric": metrics,
        "rules": [
            "Return JSON only, matching the requested keys.",
            "Do not infer hidden system behavior, response latency, voice recognition accuracy, hardware quality, or anything not visible in the supplied frames.",
            "Every observation must reference exactly one supplied evidence_id and describe only what is visibly observable.",
            "Each metric score must be an integer 1..5 and reference one or more supplied evidence_ids, or score=null with status='evidence_insufficient'.",
            "If evidence is insufficient, choose null; do not guess. Apply the rubric anchors literally.",
            "No evidence_id other than the supplied IDs may be emitted.",
            "Scores are provisional and require human review.",
        ],
        "json_shape": {
            "observations": [{"evidence_id": "F001", "observation": "what is visibly observable", "confidence": 0.0}],
            "scores": [{"metric_id": "ui_legibility", "score": 3, "status": "scored", "rationale": "evidence-linked reason", "evidence_ids": ["F001"]}],
        },
    }
    content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(instructions, ensure_ascii=False)}]
    for frame in frames:
        content.append({"type": "text", "text": f"Evidence {frame['evidence_id']} at nominal seek target {frame['timestamp_sec']:.3f}s."})
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(Path(frame["absolute_path"]))}})

    body = json.dumps({
        "model": settings.vlm_model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You are a conservative video-frame auditor. Do not invent facts. Output valid JSON only."},
            {"role": "user", "content": content},
        ],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.openai_api_key:
        headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    request = urllib.request.Request(_endpoint(settings.openai_base_url), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=settings.vlm_timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise ProviderError(f"VLM provider HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderError(f"VLM provider request failed: {exc}") from exc

    text = _response_text(payload).strip()
    if text.startswith(chr(96) * 3):
        text = text.strip(chr(96))
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"VLM returned invalid JSON: {text[:300]}") from exc
    if not isinstance(data, dict):
        raise ProviderError("VLM output must be a JSON object")
    return data
