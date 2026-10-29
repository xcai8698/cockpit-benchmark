-- PostgreSQL migration for the AIHOT cockpit-benchmark module.
-- Keep module-owned tables isolated from AIHOT's core content/event tables.
CREATE TABLE IF NOT EXISTS cockpit_benchmark_analysis (
  analysis_id            VARCHAR(32) PRIMARY KEY,
  source_url             TEXT,
  source_title           TEXT,
  source_channel         TEXT,
  vehicle_make           TEXT,
  vehicle_model          TEXT NOT NULL,
  model_year             TEXT,
  software_version       TEXT,
  scenario_id            TEXT NOT NULL,
  rubric_id              TEXT NOT NULL,
  rubric_version         TEXT NOT NULL,
  analyzer_status        TEXT NOT NULL DEFAULT 'queued'
                         CHECK (analyzer_status IN ('queued','processing','completed','failed')),
  review_status          TEXT NOT NULL DEFAULT 'pending'
                         CHECK (review_status IN ('pending','approved','rejected')),
  overall_score_100      NUMERIC(5,2),
  report_json            JSONB,
  evidence_manifest_json JSONB,
  error_message          TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_by            TEXT,
  reviewed_at            TIMESTAMPTZ,
  review_notes            TEXT,
  CHECK (review_status <> 'approved' OR (overall_score_100 IS NOT NULL AND report_json IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_cockpit_benchmark_vehicle
  ON cockpit_benchmark_analysis (vehicle_model, model_year);
CREATE INDEX IF NOT EXISTS idx_cockpit_benchmark_scenario
  ON cockpit_benchmark_analysis (scenario_id, rubric_id, rubric_version);
CREATE INDEX IF NOT EXISTS idx_cockpit_benchmark_ranking
  ON cockpit_benchmark_analysis (scenario_id, rubric_id, rubric_version, overall_score_100 DESC)
  WHERE review_status = 'approved';

CREATE TABLE IF NOT EXISTS cockpit_benchmark_review_event (
  id               BIGSERIAL PRIMARY KEY,
  analysis_id      VARCHAR(32) NOT NULL REFERENCES cockpit_benchmark_analysis(analysis_id) ON DELETE CASCADE,
  reviewer         TEXT NOT NULL,
  decision         TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
  notes            TEXT,
  report_snapshot  JSONB NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cockpit_benchmark_review_history
  ON cockpit_benchmark_review_event (analysis_id, created_at DESC);
