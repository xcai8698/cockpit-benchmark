# Cockpit Benchmark — AIHOT module skeleton

This directory is an integration scaffold, not a drop-in module. It intentionally avoids assuming the exact interfaces of a particular AIHOT checkout.

## Contents

- `src/module-contract.ts`: proposed navigation/API contract.
- `src/analyzer-client.ts`: server-side client for the separate Analyzer service.
- `src/review-policy.ts`: approval and ranking guardrails.
- `migrations/0001_cockpit_benchmark.sql`: isolated PostgreSQL tables for analyses and review events.
- `tests/review-policy.test.ts`: Vitest examples for the policy.

## Integration steps

1. Copy this folder into the AIHOT module directory appropriate to the target checkout.
2. Register it using the actual AIHOT module/server/web registries.
3. Apply the SQL migration through the host migration mechanism.
4. Configure `COCKPIT_ANALYZER_URL` and `COCKPIT_ANALYZER_API_KEY` on the server only.
5. Implement AIHOT-owned routes, upload UI, report detail/evidence UI, reviewer authorization, and ranking query.
6. Run the host project's lint, typecheck, tests, migration tests, and end-to-end validation.

## Ranking policy

Only records that are approved by a human, fully analyzed, and have an overall score should enter official rankings. Never publish a no-model report or a score unsupported by evidence IDs.

## Security caveat

The Analyzer MVP has no built-in authentication. Keep it on a trusted internal network and put it behind authentication before shared deployment. Protect video uploads and evidence frames with access control and retention rules.
