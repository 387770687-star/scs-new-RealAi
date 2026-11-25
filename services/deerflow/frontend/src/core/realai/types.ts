export type EvidenceType = "kb" | "data" | "viz" | "web" | "inference";

export interface EvidenceItem {
  id: string;
  type: EvidenceType;
  source: string;
  excerpt: string;
  meta?: Record<string, unknown>;
}

export interface EvidencePack {
  items: EvidenceItem[];
}

export interface VaultFileInfo {
  path: string;
  name: string;
  size: number;
  mtime: number;
  extension: string;
}

export interface VaultFilePreview {
  path: string;
  name: string;
  size: number;
  mtime: number;
  extension: string;
  preview_mode: "text" | "image" | "download_only";
  content?: string | null;
  truncated?: boolean;
  message?: string;
}

export interface LightAskResponse {
  answer: string;
  evidence: EvidencePack;
  run_mode: "light";
  web_search_enabled: boolean;
}

export type AgentStatus = "pending" | "running" | "completed" | "skipped" | "failed";

export interface AgentProgressStep {
  id: string;
  label: string;
  status: AgentStatus;
  message?: string;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface ReportRunResponse {
  run_mode: "report";
  phase?: "await_outline_confirm" | "completed";
  message?: string;
  preview_markdown?: string;
  vault_path?: string;
  vault_path_docx?: string;
  outline: Record<string, unknown>;
  blocks?: Record<string, unknown>[];
  evidence: EvidencePack;
  evidence_audit?: { passed: boolean; issues: string[] };
  review: { score: number; suggestions: string[]; pipeline_adapted?: boolean };
  agent_progress?: AgentProgressStep[];
  skills?: {
    writer: string;
    review: string;
    writer_valid: boolean;
    review_valid: boolean;
  };
}

export interface SkillSummary {
  id: string;
  name: string;
  description: string;
  valid: boolean;
  errors: string[];
  category?: string;
  enabled?: boolean;
  version?: string | null;
  source?: "realai" | "deerflow";
  editable?: boolean;
  read_only?: boolean;
}

export interface SkillDetail extends SkillSummary {
  body: string;
  raw: string;
  read_only?: boolean;
}

export interface RealAiSettings {
  obsidianVaultPath?: string;
  llm?: {
    provider?: string;
    modelId?: string;
    model?: string;
    baseUrl?: string;
    hasApiKey?: boolean;
    apiKeyPreview?: string;
  };
  report?: {
    outputDir?: string;
    stepConfirm?: boolean;
    intakeSkillId?: string;
    researcherSkillId?: string;
    architectSkillId?: string;
    writerSkillId?: string;
    citerSkillId?: string;
    reviewSkillId?: string;
    optimizerSkillId?: string;
  };
  search?: { webSearchEnabled?: boolean };
  data?: {
    excelRoots?: string[];
    databases?: Array<{ name: string; url: string; enabled?: boolean }>;
  };
}

export interface RealAiConfigResponse {
  vault_path: string;
  settings: RealAiSettings;
  deerflow?: { linked?: boolean; has_api_key?: boolean; model_id?: string };
  message?: string;
}

export interface SkillExecuteResponse {
  skill_id: string;
  skill_name: string;
  input: string;
  output: string;
  mode: string;
}
