import { describe, expect, it } from 'vitest';
import { assertReportCanBeApproved, isEligibleForRanking } from '../src/review-policy';
import type { AnalysisReport } from '../src/analyzer-client';

const good: AnalysisReport = {
  analysis_id: '0123456789abcdef', mode: 'openai_compatible_vlm', status: 'completed',
  rubric: { id: 'cockpit-ux', version: '1.0.0' }, overall_score_100: 82,
  scores: [{ criterion_id: 'readability', criterion_name: '界面信息可读性', score: 4, weight: 1,
    evidence_ids: ['frame_001'], rationale: '文字清晰', status: 'scored' }],
};

describe('review policy', () => {
  it('allows complete evidence-backed reports', () => expect(() => assertReportCanBeApproved(good)).not.toThrow());
  it('blocks no-model results', () => expect(() => assertReportCanBeApproved({ ...good, mode: 'no_model' })).toThrow(/without a VLM/));
  it('blocks missing score', () => expect(() => assertReportCanBeApproved({ ...good, overall_score_100: null })).toThrow(/overall score/));
  it('blocks criteria without evidence', () => expect(() => assertReportCanBeApproved({ ...good, scores: [{ ...good.scores[0], evidence_ids: [] }] })).toThrow(/incomplete criterion/));
  it('ranks only approved completed rows', () => {
    expect(isEligibleForRanking({ review_status: 'approved', analyzer_status: 'completed', overall_score_100: 82 })).toBe(true);
    expect(isEligibleForRanking({ review_status: 'pending', analyzer_status: 'completed', overall_score_100: 82 })).toBe(false);
    expect(isEligibleForRanking({ review_status: 'approved', analyzer_status: 'failed', overall_score_100: 82 })).toBe(false);
  });
});
