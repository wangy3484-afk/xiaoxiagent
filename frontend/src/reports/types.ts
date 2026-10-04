export interface ReportVersionSummary {
  report_version_id: string;
  series_id: string;
  job_id: string;
  version_number: number;
  title: string;
  scene: string;
  delivery_status: string;
  generated_at: string;
}

export interface ReportHistoryResponse {
  reports: ReportVersionSummary[];
}

export interface ReportVersionDetail extends ReportVersionSummary {
  id: string;
  brief_revision_id: string;
  report_payload: Record<string, unknown>;
  available_versions: ReportVersionSummary[];
}
