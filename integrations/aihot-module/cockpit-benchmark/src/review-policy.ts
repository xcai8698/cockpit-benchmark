import type { AnalysisReport } from './analyzer-client';

export type ReviewDecision = 'approved' | 'rejected';

/** Defense in depth: only complete, scored reports can enter an official ranking. */
export function assertReportCanBeApproved(report: AnalysisReport): void {
  if (report.mode === 'no_model') throw new Error('Cannot approve report generated without a VLM');
  if (report.overall_score_100 === null || !Number.isFinite(report.overall_score_100)) {
    throw new Error('Cannot approve a report without an overall score');
  }
  if (!report.scores.length) throw new Error('Cannot approve a report without rubric scores');
  const incomplete = report.scores.find((item) =>
    item.score === null || !Number.isFinite(item.score) || item.evidence_ids.length === 0 || item.status !== 'scored'
  );
  if (incomplete) throw new Error(`Cannot approve incomplete criterion: ${incomplete.criterion_id}`);
}

export function isEligibleForRanking(row: {
  review_status: string;
  analyzer_status: string;
  overall_score_100: number | null;
}): boolean {
  return row.review_status === 'approved'
    && row.analyzer_status === 'completed'
    && row.overall_score_100 !== null
    && Number.isFinite(row.overall_score_100);
}
