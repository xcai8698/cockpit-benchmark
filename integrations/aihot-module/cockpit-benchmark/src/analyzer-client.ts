/** Server-side client for the Cockpit Benchmark Analyzer. Never import in browser code. */
export type AnalysisStatus = {
  analysis_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  stage?: string;
  error?: string | null;
  review_status?: 'pending' | 'approved' | 'rejected';
};

export type AnalysisReport = {
  analysis_id: string;
  mode: string;
  status: string;
  rubric?: { id: string; version: string };
  scores: Array<{
    criterion_id: string;
    criterion_name: string;
    score: number | null;
    weight: number;
    evidence_ids: string[];
    rationale?: string;
    status?: 'scored' | 'insufficient_evidence' | 'error';
  }>;
  overall_score_100: number | null;
  review_status?: 'pending' | 'approved' | 'rejected';
};

export class AnalyzerClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;

  constructor(baseUrl = process.env.COCKPIT_ANALYZER_URL, apiKey = process.env.COCKPIT_ANALYZER_API_KEY) {
    if (!baseUrl) throw new Error('COCKPIT_ANALYZER_URL is required');
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.apiKey) headers.set('Authorization', `Bearer ${this.apiKey}`);
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      signal: init.signal ?? AbortSignal.timeout(15_000),
    });
    if (!response.ok) {
      const body = (await response.text()).slice(0, 500);
      throw new Error(`Analyzer request failed (${response.status}): ${body}`);
    }
    return response.json() as Promise<T>;
  }

  getStatus(id: string): Promise<AnalysisStatus> {
    return this.request(`/api/v1/analyses/${encodeURIComponent(id)}`);
  }

  getReport(id: string): Promise<AnalysisReport> {
    return this.request(`/api/v1/analyses/${encodeURIComponent(id)}/report`);
  }
}
