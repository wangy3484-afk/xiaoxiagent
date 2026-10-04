export type Scene = "acquisition" | "retention" | "campaign" | "content";

export interface BriefField<T = string | string[]> {
  value: T | null;
  status: "confirmed" | "unknown" | "inferred";
  source: "user_input" | "user_correction" | "system_inference" | "unknown";
  source_excerpt: string | null;
  asserted_as_fact: boolean;
}

export type BriefPayload = Record<string, BriefField>;

export interface SceneClassification {
  primary_scene: Scene;
  secondary_scenes: Scene[];
  rationale: string[];
  confidence: number;
  uncertainties: string[];
  user_corrected: boolean;
}

export interface ClarifyingQuestion {
  id: string;
  field: string;
  prompt: string;
  priority: "critical" | "high" | "medium";
  rationale: string;
}

export interface BriefWorkflowResponse {
  id: string;
  revision_id: string;
  revision_number: number;
  status: "draft" | "confirmed";
  brief: BriefPayload;
  classification: SceneClassification;
  ready_for_research: boolean;
  required_gaps: string[];
  clarifying_questions: ClarifyingQuestion[];
  data_boundary: {
    title: string;
    prohibited: string[];
    allowed_alternatives: string[];
  };
}
