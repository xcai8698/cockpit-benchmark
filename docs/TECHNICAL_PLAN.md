# Cockpit Benchmark MVP — Technical Plan

Version: 0.2
Date: 2026-10-29

## 1. Goal and current scope

Build a reproducible, evidence-grounded workflow for comparing cockpit experiences shown in video, with human review before results become official.

Implemented:
- Manual upload of a local video file.
- FFprobe duration check and FFmpeg frame extraction.
- Evidence IDs, seek-target timestamps, frame dimensions, and SHA-256 hashes.
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
FastAPI Analyzer -> FFprobe/FFmpeg -> sampled frames + evidence manifest
Sampled frames -> optional VLM -> normalized observations and rubric scores
No VLM configured -> evidence-only / unscored report
Report -> human review before publication

AIHOT integration scaffold is separate from the Analyzer and has not been registered against a live AIHOT checkout.

## 3. Main components

| Path | Responsibility |
|---|---|
| app/main.py | Upload, status, report, evidence and review API endpoints |
| app/video.py | FFprobe duration extraction, FFmpeg sampling and frame hashes |
| app/pipeline.py | Job orchestration, rubric loading, model-output normalization and report generation |
| app/providers/openai_compatible.py | Vision-capable OpenAI-compatible chat-completions API |
| app/models.py | Pydantic report, frame, observation, and score models |
| app/storage.py | Local JSON persistence with atomic file replacement |
| config/rubric.v1.json | Versioned first-pass rubric with intentionally limited scope |
| schemas/analysis_result.schema.json | JSON Schema for downstream integration |
| app/static/index.html | Browser UI |
| integrations/aihot-module/cockpit-benchmark | Host-side integration scaffold |

## 4. Evidence and scoring rules

- Every extracted image has an evidence ID, seek-target timestamp, dimensions, filename, and SHA-256 hash.
- The VLM may only cite evidence IDs supplied in the current analysis.
- Unknown IDs, duplicate rubric scores, malformed scores, and empty rationales are rejected or downgraded.
- A rubric metric omitted by the model becomes evidence-insufficient, not a default numeric score.
- If any metric is unscored, the overall score remains null.
- A report is provisional by default. Local review refuses approval for no-model or incomplete score sets.
- Rubric v1 is a project draft, not an industry standard and not a claim of equivalence to MISTA or J.D. Power.

## 5. API endpoints

- GET /health — health, run mode, FFmpeg/FFprobe availability.
- GET / — upload and review UI.
- POST /api/v1/analyses — upload video and create background analysis job.
- GET /api/v1/analyses?limit=20 — recent jobs.
- GET /api/v1/analyses/{id} — job status; filesystem path is omitted.
- GET /api/v1/analyses/{id}/report — structured report JSON.
- GET /api/v1/analyses/{id}/evidence/{filename} — sampled evidence frame.
- POST /api/v1/analyses/{id}/review — local review decision.
- GET /api/v1/rubric — current rubric.

## 6. Local run

Requirements: Python 3.12 recommended, FFmpeg and FFprobe on PATH. From the repository root:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

On Windows PowerShell, activate the environment with .venv\Scripts\Activate.ps1. Open http://127.0.0.1:8010.

With OPENAI_BASE_URL and VLM_MODEL unset, the app is for upload/probe/frame-extraction testing only and must not issue ratings. To enable scoring, configure an approved vision-capable OpenAI-compatible endpoint in local environment variables. Keep keys out of Git.

Docker Compose expects a local .env file and persists job/video files under ./data.

## 7. Security and deployment boundary

This is an internal-development MVP, not an internet-facing service. Before shared use:
1. Add authentication and authorization to upload, read, evidence, and review endpoints.
2. Put the service behind a private network/reverse proxy and keep API keys server-side.
3. Enforce storage quotas, retention/deletion policy, allowed media types, upload limits, and audit logs.
4. Validate that uploaded media is permitted for processing and use.
5. Treat source URLs as descriptive metadata only; the code does not fetch remote URLs.
6. Adapt the AIHOT scaffold against a specific source checkout, then run its typecheck, tests, migrations, and end-to-end tests.

## 8. Next milestones

Sprint 3 — clean verification: fresh checkout, dependency install, full Python tests, basic GitHub Actions CI, and fixes for any packaging/install mismatches.

Sprint 4 — VLM quality loop: create a small human-labelled set of authorized cockpit videos; record per-metric human scores, evidence sufficiency, and disagreement; revise rubric only with version bumps.

Sprint 5 — AIHOT integration: inspect actual module contracts, register UI/API/worker, run migration against PostgreSQL, protect endpoints, and verify ranking eligibility only admits approved complete reports.

Sprint 6 — discovery automation: add only explicitly permitted RSS or source adapters, deduplicate by canonical URL and content hash, retain provenance, and surface discovery/download failures as explicit queue states.
