import { describe, expect, it } from 'vitest';
import { assertReportCanBeApproved, isEligibleForRanking } from '../src/review-policy';
import type { AnalysisReport } from '../src/analyzer-client';

const good: AnalysisReport = {
  schema_version: '1.0.0',
  analysis_id: '0123456789abcdef',
  created_at: '2026-10-29T00:00:00+00:00',
  mode: 'openai_compatible_vlm',
  model_name: 'test-vlm',
  review_status: 'pending',
  reviewer: null,
  reviewed_at: null,
  review_notes: null,
  rubric_id: 'cockpit-basic-usability',
  rubric_version: '1.0.0',
  video_metadata: { original_filename: 'test.mp4' },
  duration_sec: 10,
  sampled_frames: [],
  observations: [],
  overall_score_100: 80,
  warnings: [],
  provenance_note: 'Provisional test report',
  scores: [{
    metric_id: 'ui_legibility',
    score: 4,
    weight: 1,
    evidence_ids: ['F001'],
    rationale: 'Visible text is clear',
    status: 'scored',
  }],
};

describe('review policy', () => {
  it('allows complete evidence-backed reports', () => expect(() => assertReportCanBeApproved(good)).not.toThrow());
  it('blocks no-model results', () => expect(() => assertReportCanBeApproved({ ...good, mode: 'no_model' })).toThrow(/without a VLM/));
  it('blocks missing score', () => expect(() => assertReportCanBeApproved({ ...good, overall_score_100: null })).toThrow(/overall score/));
  it('blocks criteria without evidence', () => expect(() => assertReportCanBeApproved({ ...good, scores: [{ ...good.scores[0], evidence_ids: [] }] })).toThrow(/incomplete metric/));
  it('ranks only approved completed rows', () => {
    expect(isEligibleForRanking({ review_status: 'approved', analyzer_status: 'completed', overall_score_100: 80 })).toBe(true);
    expect(isEligibleForRanking({ review_status: 'pending', analyzer_status: 'completed', overall_score_100: 80 })).toBe(false);
    expect(isEligibleForRanking({ review_status: 'approved', analyzer_status: 'failed', overall_score_100: 80 })).toBe(false);
  });
});
