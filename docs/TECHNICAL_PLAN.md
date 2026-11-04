# Cockpit Benchmark MVP — Technical Plan

Version: 0.2
Date: 2026-10-29

## 1. Goal and current scope

Build a reproducible, evidence-grounded workflow for comparing cockpit experiences shown in video, with human review before results become official.

Implemented:
- Manual upload of a local video file.
- FFprobe format/video/audio stream inspection and FFmpeg frame extraction.
- Long-video configuration (default 2 GB upload limit, 2-hour duration cap and 120-frame visual evidence budget).
- Audio extraction to mono 16 kHz PCM, 60-second overlapping chunks, signal-level RMS/peak/silence indicators, and optional timestamped ASR.
- Unified audiovisual timeline linking visual frames, transcript segments, and detected near-silence intervals to source-time evidence.
- Evidence IDs, seek-target timestamps, frame dimensions, and SHA-256 hashes.
- Versioned sampling manifest; optional manually supplied timestamps; opt-in FFmpeg scene-cut detection with temporal-coverage fallback.
- Optional OpenAI-compatible VLM call using sampled frames.
- Rubric-driven structured observations and scores, with validation of evidence IDs and score completeness.
- Persistent local job/report JSON, browser UI, review endpoint, and Docker/local-run setup.
- AIHOT integration scaffold proposing host-side data structures and review/ranking rules.

Not implemented yet:
- Automatic online discovery, RSS ingestion, platform downloaders, daily scheduling, or a multi-source crawler.
- Authentication/authorization in the Analyzer API.
- A production-ready AIHOT module registered and compiled against a specific AIHOT checkout.
- Automated human-vs-model agreement evaluation, multi-vehicle benchmark dashboard, CSV export, or production retention jobs.

## 2. Architecture

Browser UI -> FastAPI Analyzer -> local job/report JSON
FastAPI Analyzer -> FFprobe -> format, video stream and audio stream metadata
Video stream -> FFmpeg -> sampled frames + versioned visual sampling manifest
Audio stream -> FFmpeg -> mono 16 kHz PCM -> overlapped 60-second chunks -> signal metrics + optional timestamped ASR
Visual evidence + transcript + silence intervals -> unified AV timeline -> optional visual VLM (image-only in this iteration)
No VLM configured -> evidence-only / unscored report
Report -> human review before publication

AIHOT integration scaffold is separate from the Analyzer and has not been registered against a live AIHOT checkout.

## 3. Main components

| Path | Responsibility |
|---|---|
| app/main.py | Upload, status, report, evidence and review API endpoints |
| app/video.py | FFprobe media-stream probing, FFmpeg sampling and frame hashes |
| app/audio.py | Audio extraction, reference track, chunking, signal metrics and optional ASR |
| app/providers/openai_transcription.py | OpenAI-compatible ASR adapter |\n| app/pipeline.py | Job orchestration, rubric loading, model-output normalization and report generation |
| app/providers/openai_compatible.py | Vision-capable OpenAI-compatible chat-completions API |
| app/models.py | Pydantic report, frame, observation, and score models |
| app/storage.py | Local JSON persistence with atomic file replacement |
| config/rubric.v1.json | Versioned first-pass rubric with intentionally limited scope |
| schemas/analysis_result.schema.json | JSON Schema for downstream integration |
| app/static/index.html | Browser UI |
| integrations/aihot-module/cockpit-benchmark | Host-side integration scaffold |

## 4. Long-video audio processing

- Default upload cap is 2048 MB, maximum duration is 7200 seconds, and visual evidence cap is 120 frames; all are configurable. The reverse proxy and host storage must be configured consistently.
- At 30 minutes, 120 uniformly distributed frames provide roughly one frame every 15 seconds. This is a coarse full-video scan, not a guarantee of detecting transient interactions; event-driven local densification is a follow-up milestone.
- FFprobe records the selected video and audio stream metadata, including codec, dimensions/frame rate, audio sample rate and channels.
- FFmpeg preserves the first audio stream as a FLAC reference track at its decoded source sample rate/channel count. It separately extracts mono 16 kHz signed 16-bit PCM as the ASR/signal-analysis proxy; the temporary full-length WAV is removed after chunking.
- Audio is split into 60-second WAV chunks with 1-second overlap. Each chunk is stored with start/end time on the source-video timeline and SHA-256.
- FFmpeg `astats` and `silencedetect` provide basic peak/RMS and near-silence indicators. These are signal measurements, not subjective sound-quality scores.
- Optional audio event analysis uses a separately configured audio-input-capable Chat Completions model. It labels candidate speech, navigation prompts, assistant speech, alert tones, turn-signal clicks, button feedback, music and cabin noise with chunk-relative model-estimated timestamps that are offset to the source-video timeline.
- Audio event analysis has an independent per-video chunk budget (`AUDIO_EVENT_MAX_CHUNKS`, default 40). Budget-skipped and failed chunks are disclosed in the manifest; a 30-minute video normally fits within the default budget at 60-second chunks with 1-second overlap.
- Optional ASR uses an OpenAI-compatible `/audio/transcriptions` endpoint, requests verbose segment timestamps, offsets each segment into the source-video timeline, and deduplicates exact repeated text in chunk overlaps. If only whole-chunk text is returned, timestamp precision is explicitly marked as `chunk_window`.
- Transcription is optional and can incur provider charges. Failed ASR chunks are reported without discarding the visual evidence.
- `av_timeline` links visual frame timestamps, ASR transcript segments, detected near-silence intervals and optional sound-event candidates. Sound-event model timestamps are estimates, not frame-accurate measurements; the source audio chunk is retained as the evidence reference for replay.
- The visual VLM and audio event model are still independent specialist passes. The timeline aligns their evidence but does not yet perform joint audiovisual consistency scoring. A later fusion evaluator must compare visual observations with timestamped audio events/transcripts and cite both modalities before a cross-modal score can be produced.

## 5. Evidence and scoring rules

- Every extracted image has an evidence ID, seek-target timestamp, dimensions, filename, and SHA-256 hash.
- Each report records `sampling_manifest` with policy/version, interval and frame cap, selected timestamps, scene candidates, supplemental timestamp disposition, maximum gap, and coverage gaps.
- `uniform_v1` remains the default and preserves historical fixed-interval behavior. `scene_aware_v1` is opt-in because it adds a full video decode pass; it detects coarse visual cuts, not semantic interactions.
- Uploaders may provide supplemental timestamps as comma/semicolon-separated seconds. Supplemental frames share the global `MAX_FRAMES` cap and are prioritized; out-of-range timestamps are ignored with warnings.
- The VLM may only cite evidence IDs supplied in the current analysis.
- Unknown IDs, duplicate rubric scores, malformed scores, and empty rationales are rejected or downgraded.
- A rubric metric omitted by the model becomes evidence-insufficient, not a default numeric score.
- If any metric is unscored, the overall score remains null.
- A report is provisional by default. Local review refuses approval for no-model or incomplete score sets.
- Rubric v1 is a project draft, not an industry standard and not a claim of equivalence to MISTA or J.D. Power.

## 6. API endpoints

- GET /health — health, run mode, FFmpeg/FFprobe availability.
- GET / — upload and review UI.
- POST /api/v1/analyses — upload video and create background analysis job.
- GET /api/v1/analyses?limit=20 — recent jobs.
- GET /api/v1/analyses/{id} — job status; filesystem path is omitted.
- GET /api/v1/analyses/{id}/report — structured report JSON.
- GET /api/v1/analyses/{id}/evidence/{filename} — sampled evidence frame.
- GET /api/v1/analyses/{id}/audio/{filename} — lossless source audio track or timestamped analysis chunk.
- POST /api/v1/analyses/{id}/review — local review decision.
- GET /api/v1/rubric — current rubric.

## 7. Local run

Requirements: Python 3.12 recommended, FFmpeg and FFprobe on PATH. From the repository root:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

On Windows PowerShell, activate the environment with .venv\Scripts\Activate.ps1. Open http://127.0.0.1:8010.

With OPENAI_BASE_URL and VLM_MODEL unset, the app is for upload/probe/frame-extraction testing only and must not issue ratings. To enable scoring, configure an approved vision-capable OpenAI-compatible endpoint in local environment variables. Keep keys out of Git.

Docker Compose expects a local .env file and persists job/video files under ./data.

## 8. Security and deployment boundary

This is an internal-development MVP, not an internet-facing service. Before shared use:
1. Add authentication and authorization to upload, read, evidence, and review endpoints.
2. Put the service behind a private network/reverse proxy and keep API keys server-side.
3. Enforce storage quotas, retention/deletion policy, allowed media types, upload limits, and audit logs.
4. Validate that uploaded media is permitted for processing and use.
5. Treat source URLs as descriptive metadata only; the code does not fetch remote URLs.
6. Adapt the AIHOT scaffold against a specific source checkout, then run its typecheck, tests, migrations, and end-to-end tests.

## 9. Sampling policy and acceptance notes

- Default stays on `uniform_v1` until a fixed set of videos demonstrates that scene-aware sampling improves evidence recall without unfairly changing temporal coverage.
- `scene_aware_v1` uses a downsampled proxy stream and an FFmpeg scene score threshold. A scene cut is only a visual transition candidate, not proof of an interaction or a state change.
- For benchmark comparisons, lock the sampling policy/version, frame cap, interval, and supplemental timestamps for all comparable videos. Record policy changes as a benchmark protocol change, not as an invisible implementation detail.
- Review short interactions (turn-signal telltales, popups, transient warnings) using explicit supplemental timestamps until a validated interaction/event detector exists.
- The planner is deterministic for a given duration, configuration, scene-candidate list, and supplemental timestamp list. FFmpeg version and source-video hash should also be pinned in a production audit record.

## 10. Next milestones

Sprint 6 — audiovisual fusion evaluator: compare timestamped visual observations with ASR and sound-event candidates on the shared source timeline; implement cross-modal consistency metrics with evidence references from both modalities and a human-labelled validation set.

Sprint 7 — long-video event sampling: use the coarse visual scan, ASR and audio-event timeline to allocate dense local visual/audio evidence around candidate events, while recording the selection policy and coverage gaps.

Sprint 3 — CI hardening: keep the GitHub Actions Python suite green, add tests for upload boundaries and evidence/report invariants, and fix packaging issues revealed by clean CI runs.

Sprint 4 — VLM quality loop: create a small human-labelled set of authorized cockpit videos; record per-metric human scores, evidence sufficiency, and disagreement; revise rubric only with version bumps.

Sprint 5 — AIHOT integration: inspect actual module contracts, register UI/API/worker, run migration against PostgreSQL, protect endpoints, and verify ranking eligibility only admits approved complete reports.

Sprint 6 — audiovisual evaluator: add configurable audio-capable model adapter for sound-event classification and joint AV reasoning; require timestamped visual/audio evidence references, and build a human-labelled evaluation set for timing, event recall and cross-modal consistency.

Sprint 7 — discovery automation: add only explicitly permitted RSS or source adapters, deduplicate by canonical URL and content hash, retain provenance, and surface discovery/download failures as explicit queue states.
