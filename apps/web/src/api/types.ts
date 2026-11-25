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

export interface ChartSpec {
  type: string;
  title?: string;
  categories?: string[];
  series?: Array<{ name: string; data: number[] }>;
  evidence_id?: string;
}

export interface DataTable {
  id: string;
  title: string;
  columns: string[];
  rows: Record<string, unknown>[];
  evidence_id?: string;
}

export interface EntityProfile {
  name: string;
  type?: string;
  summary_bullets?: string[];
  related?: string[];
  metrics?: Record<string, unknown>;
  source_entity_path?: string;
  match_terms?: string[];
  pipelines?: string[];
  sections?: string[];
}

export type FilterOp = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains";

export interface FilterCondition {
  id: string;
  field_key: string;
  field_label: string;
  op: FilterOp;
  value: string;
  unit?: string;
  value_normalized?: number | string;
}

export interface FilterDraft {
  logic: "and";
  conditions: FilterCondition[];
  title_hint?: string;
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
  preview_mode:
    | "text"
    | "image"
    | "pdf"
    | "document"
    | "spreadsheet"
    | "download_only";
  content?: string | null;
  truncated?: boolean;
  message?: string;
  page_count?: number;
  sheets?: Array<{
    name: string;
    columns: string[];
    rows: unknown[][];
    total_rows: number;
    truncated: boolean;
  }>;
}

export type KnowledgeType =
  | "document"
  | "dataset"
  | "media"
  | "knowledge_card"
  | "entity"
  | "metric"
  | "outcome";

export type KnowledgeSourceStatus = "raw" | "curated" | "derived" | "generated";
export type KnowledgeQualityStatus = "ready" | "needs_attention";

export interface KnowledgeCatalogFile {
  path: string;
  name: string;
  extension: string;
  size: number;
  role?: "original" | "searchable_text" | "structured_data" | "file";
  role_label?: string;
}

export interface KnowledgeCatalogItem extends VaultFileInfo {
  id: string;
  title: string;
  summary: string;
  knowledge_type: KnowledgeType;
  knowledge_type_label: string;
  source_status: KnowledgeSourceStatus;
  source_status_label: string;
  quality_status: KnowledgeQualityStatus;
  quality_status_label: string;
  business_tags: string[];
  formats: string[];
  files: KnowledgeCatalogFile[];
  original_path?: string | null;
  preview_mode: "text" | "image" | "download_only";
}

export interface VaultImportJobItem {
  name: string;
  size?: number;
  status: "pending" | "running" | "completed" | "failed" | string;
  stage?: string;
  progress?: number;
  message: string;
  outputs?: string[];
  category?: string;
}

export interface VaultImportJob {
  id: string;
  created_at: number;
  updated_at: number;
  status: "queued" | "running" | "completed" | "failed" | string;
  total: number;
  done: number;
  failed: number;
  stage: string;
  progress: number;
  current_file?: string | null;
  message: string;
  error?: string | null;
  items: VaultImportJobItem[];
}

export interface KnowledgeCatalogResponse {
  items: KnowledgeCatalogItem[];
  count: number;
  total: number;
  filtered_total: number;
  offset: number;
  limit: number;
  type_counts: Record<KnowledgeType, number>;
  source_counts: Record<KnowledgeSourceStatus, number>;
  quality_counts: Record<KnowledgeQualityStatus, number>;
  business_tag_counts: Record<string, number>;
  type_labels: Record<KnowledgeType, string>;
  source_labels: Record<KnowledgeSourceStatus, string>;
  quality_labels: Record<KnowledgeQualityStatus, string>;
}

export type WorkbenchIntent = "ask" | "data" | "research";

export interface SkillRuntimeUse {
  id: string;
  name: string;
  version?: string | null;
  trigger: "selected" | "slash" | "auto_rule" | string;
  source?: string;
}

export interface SkillDraft {
  skill_id: string;
  name: string;
  description: string;
  body: string;
  raw: string;
}

export interface SkillOptimizeResponse {
  answer: string;
  draft: SkillDraft;
  can_publish: boolean;
  publish_hint?: string;
  forked?: boolean;
  source_skill_id?: string;
  trajectory?: string[];
}

export interface LightAskResponse {
  answer: string;
  conclusion?: string;
  tables?: DataTable[];
  chart_spec?: ChartSpec | null;
  entity_profile?: EntityProfile | null;
  awaiting_confirm?: boolean;
  confirm_kind?: string;
  filter_draft?: FilterDraft | null;
  message_id?: string;
  data_query?: {
    mode?: string;
    candidates?: number;
    hits?: number;
    match_terms?: string[];
    sql?: string | null;
  };
  trajectory?: string[];
  evidence: EvidencePack;
  run_mode: "light";
  intent?: WorkbenchIntent;
  web_search_enabled: boolean;
  web_search_mode?: "off" | "auto" | "force";
  vision_mode?: "off" | "auto" | "force";
  scope_paths?: string[];
  session_id?: string;
  skill_used?: SkillRuntimeUse | null;
}

export type AgentStatus = "pending" | "running" | "completed" | "skipped" | "failed";

export interface StepTraceItem {
  kind: "action" | "llm" | "llm_pending" | string;
  at?: number;
  title: string;
  summary?: string;
  detail?: string;
  system?: string;
  prompt?: string;
  reply?: string;
  reasoning?: string | null;
}

export interface AgentProgressStep {
  id: string;
  label: string;
  status: AgentStatus;
  message?: string;
  started_at?: number | null;
  finished_at?: number | null;
  /** Bound Skill package id, e.g. strategic-planning-writer */
  skill_id?: string;
  skill_name?: string;
  skill_valid?: boolean;
  /** Package reference files loaded with the Skill (paths) */
  references?: string[];
  /** Package script files listed with the Skill (not executed by default) */
  scripts?: string[];
  /** Runtime tools used in this step, e.g. 知识检索 / 问数 */
  tools?: string[];
  /** Per-step process log (actions + LLM turns); only present on new runs */
  trace?: StepTraceItem[];
}

export interface KnowledgeCard {
  id: string;
  kind: string;
  type?: string;
  title: string;
  source: string;
  excerpt: string;
  meta?: Record<string, unknown>;
  table?: unknown;
  columns?: unknown;
}

export interface Scorecard {
  total?: number;
  verdict?: string;
  dimensions?: Array<{ name: string; score: number; reason?: string }>;
  issues?: Array<{ severity?: string; chapter?: string; detail?: string }>;
  weak_dimensions?: string[];
  fallback?: boolean;
}

export interface CitationLedgerEntry {
  n?: number;
  id?: string;
  label?: string;
  source_type?: string;
  excerpt?: string;
  url?: string;
}

export interface ReportRunResponse {
  run_mode: "report";
  phase?:
    | "running"
    | "await_outline_confirm"
    | "await_chapter_confirm"
    | "paused"
    | "cancelled"
    | "completed";
  message?: string;
  preview_markdown?: string;
  vault_path?: string;
  vault_path_docx?: string;
  vault_path_pdf?: string;
  outline: Record<string, unknown>;
  blocks?: Record<string, unknown>[];
  evidence: EvidencePack;
  knowledge_cards?: KnowledgeCard[];
  citation_ledger?: CitationLedgerEntry[];
  scorecard?: Scorecard;
  scorecards?: Scorecard[];
  chinese_chars?: number;
  min_chars?: number;
  chars_met?: boolean;
  evidence_weak?: boolean;
  completion_note?: string;
  evidence_audit?: { passed: boolean; issues: string[] };
  review?: { score?: number; suggestions?: string[]; pipeline_adapted?: boolean; scorecard?: Scorecard; verdict?: string };
  agent_progress?: AgentProgressStep[];
  skills?: Record<string, string | boolean>;
  next_chapter_index?: number;
}

export interface WritingIntakeQuestion {
  id: string;
  field?: string;
  prompt: string;
  why?: string;
  answer?: string;
  skipped?: boolean;
}

export interface WritingIntake {
  status?: "pending" | "running" | "await_answers" | "done" | string;
  mode?:
    | "smart_gap_fill"
    | "auto_skipped"
    | "local_questions"
    | "questions"
    | "user_skipped"
    | string;
  local_context?: {
    time_scope?: string[];
    regions?: string[];
    business_scope?: string[];
    goals?: string[];
    audience?: string[];
    hard_constraints?: string[];
  };
  missing_fields?: string[];
  evidence_brief?: Array<{
    id?: string;
    source?: string;
    title?: string;
    excerpt?: string;
  }>;
  questions?: WritingIntakeQuestion[];
  user_provided_facts?: Array<{
    id?: string;
    statement?: string;
    question?: string;
    answer?: string;
    source?: string;
  }>;
  skill_id?: string;
  diagnostics?: {
    latest?: {
      started_at?: number;
      finished_at?: number;
      duration_ms?: number;
      model_called?: boolean;
      model_role?: string;
      max_tokens?: number;
      timeout_seconds?: number;
      retrieved_count?: number;
      missing_fields?: string[];
      parse_error?: string | null;
      model_error?: string | null;
      traces?: StepTraceItem[];
    };
    attempts?: Array<Record<string, unknown>>;
  };
}

export interface WritingTask {
  id: string;
  created_at: number;
  updated_at: number;
  goal: string;
  status: string;
  step_confirm: boolean;
  outline: Record<string, unknown>;
  progress: AgentProgressStep[];
  result: ReportRunResponse | null;
  error: string | null;
  artifact_ids: string[];
  meta?: Record<string, unknown>;
  report_type?: string;
  template_id?: string | null;
  outline_confirm_required?: boolean;
  audience?: string;
  scope_paths?: string[];
  knowledge_cards?: KnowledgeCard[];
  scorecards?: Scorecard[];
  intake?: WritingIntake | null;
  skill_profile?: {
    id: string;
    name: string;
    description?: string;
    version?: string | null;
    body?: string;
    source?: string;
    category?: string;
  } | null;
}

export interface Artifact {
  id: string;
  created_at: number;
  kind: string;
  title: string;
  content: Record<string, unknown>;
  evidence_ids: string[];
  source_task?: string | null;
}

export interface Metric {
  id: string;
  name: string;
  aliases: string[];
  formula?: string | null;
  unit?: string | null;
  dimensions: string[];
  authority_table?: string | null;
  notes?: string | null;
}

export interface EvalSuite {
  id: string;
  name: string;
  description?: string;
  kind?: string | null;
  case_count?: number;
  cases?: EvalCase[];
}

export interface EvalCase {
  id: string;
  suite_id: string;
  created_at?: number;
  updated_at?: number | null;
  version?: number;
  question: string;
  expect_keywords: string[];
  expect_evidence: boolean;
  expect_number?: number | null;
  number_tolerance?: number | null;
  expect_answer?: string | null;
  answer_match_mode?: "contains" | "exact" | "regex" | string;
  expect_unit?: string | null;
  expect_table?: {
    columns?: string[];
    rows?: Array<Record<string, unknown> | unknown[]>;
    min_rows?: number;
    match_mode?: "subset" | "exact" | string;
  };
  expect_source_paths?: string[];
  rubric?: Record<string, unknown>;
  fixture?: { image_paths?: string[]; scope_paths?: string[] };
  tags?: string[];
  difficulty?: "easy" | "medium" | "hard" | string;
  intent?: string;
  category?: string;
  mode?: string;
  expect_evidence_kinds?: string[];
  expect_min_rows?: number | null;
  skip_if?: string | null;
  notes?: string;
}

export interface EvalCaseResult {
  case_id?: string;
  question?: string;
  category?: string;
  mode?: string;
  passed?: boolean;
  skipped?: boolean;
  reasons?: string[];
  answer_preview?: string;
  answer?: string;
  response?: Record<string, unknown>;
  evidence_count?: number;
  duration_ms?: number;
  model_calls?: Array<{
    id?: string;
    model?: string;
    provider?: string;
    latency_ms?: number | null;
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    success?: boolean;
    error?: string | null;
  }>;
  meta?: Record<string, unknown>;
}

export interface EvalRegression {
  base_run_id?: string;
  new_run_id?: string;
  new_failures?: Array<{
    case_id?: string;
    question: string;
    reasons?: string[];
    failure_stage?: string;
  }>;
  fixed?: Array<{ case_id?: string; question: string; reasons?: string[] }>;
  still_failing?: Array<{ case_id?: string; question?: string; reasons?: string[] }>;
  score_changes?: Array<{
    case_id?: string;
    question?: string;
    before?: number;
    after?: number;
    delta?: number;
  }>;
  base_pass_rate?: number | null;
}

export interface EvalRun {
  id: string;
  suite_id: string;
  status: string;
  passed?: number | null;
  total?: number | null;
  skipped?: number | null;
  pass_rate?: number | null;
  results?: EvalCaseResult[];
  created_at: number;
  finished_at?: number | null;
  mode?: string;
  web_search_enabled?: boolean;
  model_override?: string | null;
  skill_overrides?: Record<string, string>;
  snapshot?: Record<string, unknown>;
  progress?: { done?: number; total?: number };
  metrics?: {
    avg_score?: number | null;
    avg_latency_ms?: number | null;
    p95_latency_ms?: number | null;
    prompt_tokens?: number;
    completion_tokens?: number;
    model_calls?: number;
    failure_stages?: Record<string, number>;
  };
  options?: Record<string, unknown>;
  error?: string | null;
  heartbeat_at?: number | null;
  cancel_requested?: boolean;
  category_stats?: Record<string, { passed?: number; failed?: number; skipped?: number; total?: number }>;
  regression?: EvalRegression | null;
  compare_base_run_id?: string | null;
}

export type SkillGroup = "deerflow_builtin" | "business";

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
  /** deerflow_builtin=内置只读；business=业务场景可维护 */
  group?: SkillGroup;
}

export interface SkillPackageFile {
  path: string;
  size: number;
  kind: "main" | "reference" | "script" | "template" | "asset" | "other" | string;
  text?: boolean;
}

export interface SkillFileContent {
  path: string;
  size: number;
  kind: string;
  text: boolean;
  content: string | null;
  message?: string | null;
}

export interface SkillDetail extends SkillSummary {
  body: string;
  raw: string;
  read_only?: boolean;
  files?: SkillPackageFile[];
}

export interface RealAiSettings {
  obsidianVaultPath?: string;
  llm?: {
    protocol?: "openai_compatible" | "anthropic";
    provider?: string;
    modelId?: string;
    model?: string;
    baseUrl?: string;
    hasApiKey?: boolean;
    apiKeyPreview?: string;
    apiKey?: string;
    models?: Array<{ id: string; label?: string; apiModel: string }>;
    roles?: {
      primary?: string;
      fast?: string;
      vision?: string;
      fallback?: string;
    };
    fastModel?: string;
    visionModel?: string;
    fallbackModel?: string;
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
    optimizerMaxRounds?: number;
    optimizerPassScore?: number;
  };
  search?: {
    webSearchMode?: "off" | "auto" | "force";
    webSearchEnabled?: boolean;
    webSearchSkillId?: string;
    visionMode?: "off" | "auto" | "force";
  };
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

export class ApiError extends Error {
  status: number;
  kind: "network" | "not_ready" | "business";

  constructor(message: string, status = 0, kind: ApiError["kind"] = "business") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
  }
}
