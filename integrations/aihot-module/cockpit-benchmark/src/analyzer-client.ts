/** Server-side client for the Cockpit Benchmark Analyzer. Never import in browser code. */
export type AnalysisStatus = {
  analysis_id: string;
  status: 'queued' | 'processing' | 'completed' | 'completed_unscored' | 'failed';
  stage?: string;
  error?: string | null;
  review_status?: 'pending' | 'approved' | 'rejected';
};

export type AnalysisReport = {
  schema_version: string;
  analysis_id: string;
  created_at: string;
  mode: 'openai_compatible_vlm' | 'no_model';
  model_name: string | null;
  review_status: 'pending' | 'approved' | 'rejected';
  reviewer: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  rubric_id: string;
  rubric_version: string;
  video_metadata: {
    original_filename: string;
    vehicle_make?: string | null;
    vehicle_model?: string | null;
    model_year?: string | null;
    software_version?: string | null;
    scenario?: string | null;
    source_url?: string | null;
  };
  duration_sec: number;
  sampled_frames: Array<{
    evidence_id: string;
    timestamp_sec: number;
    timestamp_semantics: 'ffmpeg_seek_target';
    file_name: string;
    sha256: string;
    mime_type: 'image/jpeg';
    width: number | null;
    height: number | null;
    source_video: string;
  }>;
  observations: Array<{
    evidence_id: string;
    observation: string;
    confidence: number | null;
  }>;
  scores: Array<{
    metric_id: string;
    score: number | null;
    status: 'scored' | 'evidence_insufficient';
    rationale: string;
    evidence_ids: string[];
    weight: number;
  }>;
  overall_score_100: number | null;
  warnings: string[];
  provenance_note: string;
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
