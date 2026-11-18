export type SessionStatus =
  | "RUNNING"
  | "PAUSED_C2"
  | "TRIPPED_LOOP"
  | "TRIPPED_BUDGET"
  | "COMPLETED"
  | "TERMINATED";

export type AgentFramework = "langgraph" | "lcel" | "crewai" | "autogpt" | "mcp" | "custom";

export type ViewMode = "ALL" | "TOPOLOGY" | "C2_LAB" | "FINOPS" | "GUIDE" | "DOCS";

export interface TeamMemberInfo {
  name: string;
  role: string;
  email?: string;
  avatar_url?: string;
  github?: string;
  linkedin?: string;
  bio?: string;
}

export interface DocsConfigResponse {
  is_public: boolean;
  visibility_mode: "PUBLIC" | "RESTRICTED" | "SCHEDULED";
  scheduled_start: string | null;
  scheduled_end: string | null;
  last_updated_at: string;
  updated_by: string;
  project_name: string;
  tagline: string;
  team: TeamMemberInfo[];
}

export interface AgentSession {
  session_id: string;
  tenant_id: string;
  workspace_id: string;
  workflow_id: string;
  agent_name: string;
  framework: AgentFramework;
  status: SessionStatus;
  budget_cap_usd: number;
  accumulated_cost_usd: number;
  latest_checkpoint_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArgusSpan {
  session_id: string;
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  dotted_order: string;
  name: string;
  span_kind: string;
  operation_name: string;
  framework: string;
  model_name?: string;
  provider_name?: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  ttft_ms?: number;
  latency_ms: number;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown>;
  state_diff?: Array<{ op: string; path: string; value?: unknown }>;
  attributes: Record<string, string | number | boolean>;
  redacted?: boolean;
  started_at: string;
  ended_at?: string;
}

export interface PendingToolCall {
  tool_call_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  is_destructive: boolean;
  security_risk?: string | null;
  request_digest_sha256?: string;
  created_at?: string;
}

export interface ResolvedToolOverride {
  session_id: string;
  tool_call_id: string;
  tool_name: string;
  decision: "approve" | "edit" | "mock" | "reject";
  request_digest_sha256: string;
  should_execute: boolean;
  effective_payload: Record<string, unknown>;
  status_message: string;
  operator_id: string;
  resolved_at: string;
}

export interface CheckpointRecord {
  checkpoint_id: string;
  parent_checkpoint_id: string | null;
  tenant_id: string;
  workspace_id: string;
  session_id: string;
  node_name: string;
  step_index: number;
  memory_state: Record<string, unknown>;
  pending_tool_call: PendingToolCall | null;
  created_at: string;
}

export interface AuditLogEntry {
  audit_id: string;
  tenant_id: string;
  workspace_id: string;
  session_id: string;
  actor_id: string;
  actor_role: string;
  event_type: string;
  payload: Record<string, unknown>;
  payload_sha256: string;
  prev_entry_hash: string;
  entry_hash: string;
  created_at: string;
}

export type AuditViolationType =
  | "GENESIS_VIOLATION"
  | "PAYLOAD_DIGEST_MISMATCH"
  | "ENVELOPE_DIGEST_MISMATCH"
  | "CHAIN_LINK_BROKEN";

export interface AuditVerificationResult {
  session_id: string;
  is_valid: boolean;
  total_entries: number;
  genesis_hash: string;
  tip_hash?: string | null;
  tampered_entry_index?: number | null;
  tampered_audit_id?: string | null;
  violation_type?: AuditViolationType | null;
  violation_details?: string | null;
  verified_at: string;
}

export interface AuditLogResponse {
  session_id: string;
  chain_verified: boolean;
  entries: AuditLogEntry[];
  verification_report?: AuditVerificationResult | null;
}

export interface AuditQueryResponse {
  entries: AuditLogEntry[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface WorkflowROIAttribution {
  session_id: string;
  workflow_id: string;
  assigned_business_value_usd: number;
  realized_business_value_usd?: number;
  llm_cost_usd: number;
  tool_cost_usd: number;
  infra_cost_usd: number;
  c2_intervention_cost_usd: number;
  wasted_loop_cost_usd: number;
  total_cost_usd: number;
  net_roi_usd: number;
  roi_percentage: number;
  task_completed: boolean;
  task_completion_score: number;
  tool_correctness_score: number;
  wall_clock_duration_seconds?: number;
  c2_interventions_count?: number;
  total_spans_evaluated?: number;
}

export interface TrajectoryEvaluationReport {
  session_id: string;
  tenant_id: string;
  workspace_id: string;
  total_steps: number;
  llm_steps: number;
  tool_steps: number;
  expected_tools: string[];
  used_tools: string[];
  matched_tools: string[];
  missing_tools: string[];
  unexpected_tools: string[];
  tool_correctness_score: number;
  goal_keywords: string[];
  matched_keywords: string[];
  task_completed: boolean;
  task_completion_score: number;
  fatal_errors_detected: string[];
  diagnostic_summary: string;
}

export interface FleetROISummary {
  tenant_id: string;
  workspace_id: string;
  total_sessions: number;
  completed_sessions: number;
  total_fleet_spend_usd: number;
  total_realized_value_usd: number;
  net_fleet_roi_usd: number;
  fleet_roi_percentage: number;
  total_wasted_loop_cost_usd: number;
  average_completion_score: number;
  average_tool_score: number;
  sessions: WorkflowROIAttribution[];
}

export interface ModelBenchmarkEntry {
  model_name: string;
  display_name?: string;
  provider: string;
  open_weights?: boolean;
  gaia_accuracy: number;
  open_llm_score?: number;
  ttft_ms: number;
  throughput_tokens_sec: number;
  input_cost_per_1k: number;
  output_cost_per_1k: number;
  context_window_tokens?: number;
  aliases?: string[];
}

export interface DowngradeRecommendation {
  candidate_model: string;
  display_name?: string;
  provider: string;
  open_weights?: boolean;
  cost_savings_pct: number;
  latency_reduction_pct: number;
  throughput_gain_pct?: number;
  benchmark_accuracy_delta: number;
  candidate_gaia_accuracy?: number;
  is_pareto_optimal?: boolean;
  strategy_tier?: string;
  input_cost_per_1k?: number;
  output_cost_per_1k?: number;
}

export interface SessionCandidateProjection {
  candidate_model: string;
  display_name: string;
  provider: string;
  open_weights: boolean;
  projected_session_cost_usd: number;
  session_dollar_savings_usd: number;
  cost_savings_pct: number;
  latency_reduction_pct: number;
  projected_annual_savings_10k_sessions_usd: number;
  strategy_tier: string;
  is_pareto_optimal: boolean;
}

export interface SessionDowngradeReport {
  session_id: string;
  active_model: string;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  current_session_cost_usd: number;
  recommendations: SessionCandidateProjection[];
}

export type ContainerAnomalyType =
  | "OOM_KILL"
  | "EXIT_CODE_137"
  | "SIGKILL"
  | "SIGTERM"
  | "WORKER_TIMEOUT"
  | "PANIC_CRASH"
  | "SEGMENTATION_FAULT";

export interface ContainerLog {
  log_id: string;
  timestamp: string;
  log_group: string;
  log_stream: string;
  severity: string;
  message: string;
  is_container_anomaly: boolean;
  anomaly_type?: ContainerAnomalyType | null;
  trace_id: string | null;
  span_id: string | null;
  session_id?: string | null;
}

export interface CloudWatchQueryResponse {
  total_count: number;
  anomalies_count: number;
  correlated_count: number;
  limit: number;
  offset: number;
  logs: ContainerLog[];
}

export interface WorkerLease {
  session_id: string;
  tenant_id: string;
  workspace_id: string;
  worker_id: string;
  ttl_seconds: number;
  renewed_at: string;
  expires_at: string;
  ttl_remaining_seconds: number;
  is_expired: boolean;
  session_status?: SessionStatus | null;
}

export interface ReapLeasesResponse {
  reaped_session_ids: string[];
  reaped_count: number;
  dry_run: boolean;
}

export type EvalDatasetType = "all" | "hallucination" | "tool_calling" | "trajectory";

export interface PhoenixEvalDatasets {
  hallucination_records: Record<string, unknown>[];
  tool_calling_records: Record<string, unknown>[];
  trajectory_records: Record<string, unknown>[];
}

export interface OpenInferenceExportResponse {
  session_id: string;
  span_count: number;
  openinference_spans: Record<string, unknown>[];
  dataframe_records: Record<string, unknown>[];
  eval_datasets: PhoenixEvalDatasets;
}

export interface StorageDiagnostics {
  db_path: string;
  journal_mode: string;
  page_size: number;
  page_count: number;
  freelist_count: number;
  database_size_bytes: number;
  wal_size_bytes: number;
  total_size_bytes: number;
  integrity_check: string;
  table_counts: {
    sessions: number;
    checkpoints: number;
    spans: number;
    budgets: number;
    audit_entries: number;
  };
}

export interface ReadyzResponse {
  status: "READY" | "DEGRADED";
  service: string;
  storage_backend: "memory" | "sqlite" | "postgres";
  diagnostics?: StorageDiagnostics;
}
