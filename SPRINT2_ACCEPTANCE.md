# Sprint 2 Acceptance Report

## Delivered in this repository

- FastAPI Analyzer service for local video upload, video probing/extraction, job status, report retrieval, evidence frame retrieval, and human review.
- SHA-256 evidence frame manifest with seek-target timestamps.
- Versioned JSON rubric and analysis result schema.
- OpenAI-compatible VLM adapter. Without a configured VLM, the pipeline extracts frames but does not issue scores.
- Scoring normalization that rejects unknown evidence IDs, duplicate scores, malformed values, and missing rationales; omitted rubric metrics become evidence-insufficient.
- Local browser UI for upload, evidence review, and JSON report viewing.
- Python API/core regression tests.
- AIHOT integration scaffold: SQL migration, server-side Analyzer client, module contract, review/ranking policy, and Vitest test source.
- Docker and local launch examples.

## Verification status

GitHub Actions workflow run #1 passed on commit 344ab76778db7eabf37c032d5b31085640ddc2de. The workflow checked out the committed repository, installed Python dependencies, and executed pytest -q successfully. The TypeScript/Vitest tests have not been run; the SQL migration has not been applied to PostgreSQL; and the module has not been compiled against an actual AIHOT checkout.

## Important limitations

- No video discovery/crawler or daily schedule is implemented in this MVP; videos are manually uploaded.
- Analyzer API has no authentication, so it must remain local/internal and be placed behind authentication before shared deployment.
- AIHOT code is an integration scaffold, not a drop-in production module. Registration routes and UI must be adapted to the exact target AIHOT checkout.
- No real VLM result or score-quality claim is certified by this acceptance report.
- Use only videos you are authorized to process, and follow source-platform terms and privacy requirements.

## Next verification gates

1. Keep the Python CI green and expand regression coverage as the MVP evolves.
2. Configure an approved VLM endpoint and manually validate multiple cockpit scenes against human ratings.
3. Integrate the scaffold into the actual AIHOT checkout, then run its typecheck, tests, and smoke tests.
4. Apply the SQL migration to a disposable PostgreSQL database and verify migration/recovery procedures.
5. Add authenticated access, retention policy, and allowed-source ingest before any shared deployment.
