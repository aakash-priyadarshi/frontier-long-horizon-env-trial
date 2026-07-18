export type Provider = {
  provider: string;
  display_name: string;
  configured: boolean;
  ready: boolean;
  models: ProviderModel[];
  capabilities: {
    temperature: boolean;
    reasoning_effort: boolean;
    deterministic: boolean;
    custom_model: boolean;
    custom_base_url: boolean;
    connection_test: boolean;
    model_discovery: boolean;
    tool_probe: boolean;
  };
  credential: {
    state: "not_required" | "missing" | "available";
    source: "not_required" | "missing" | "environment" | "local_env" | "session" | "os_vault";
    required: boolean;
  };
  endpoint: ProviderCheckStatus;
  authentication: ProviderCheckStatus;
  model_discovery: ProviderCheckStatus & { count: number };
  tool_calling: ToolCompatibility;
  base_url: string | null;
};

export type ProviderCheckStatus = {
  state: string;
  tested_at: string | null;
  latency_ms?: number;
};

export type ToolCompatibility = {
  state: "passed" | "failed" | "not_tested";
  tested_at: string | null;
  model?: string;
  model_digest?: string | null;
  error_code?: string | null;
  invalidated?: boolean;
  profile?: ToolProbeOptions | null;
  observed?: {
    finish_reason?: string | null;
    tool_call_count: number;
    returned_text: boolean;
    returned_reasoning: boolean;
  } | null;
};

export type ToolProbeOptions = {
  context_window: number;
  max_output_tokens: number;
  retry_output_tokens: number | null;
  timeout_seconds: number;
  temperature: number;
  thinking: "default" | "off" | "low" | "medium" | "high";
  prompt_style: "strict" | "minimal" | "schema_guided";
};

export type ProviderModel = {
  id: string;
  display_name: string;
  size?: number;
  digest?: string;
  details?: { family?: string; parameter_size?: string; quantization_level?: string };
  inference_capabilities?: {
    reasoning_effort: boolean;
  };
  tool_compatibility?: ToolCompatibility;
  tool_support?: {
    profile_id: string;
    profile_name: string;
    support: "locally_verified" | "profile_available" | string;
    notes: string;
  } | null;
  tool_limitation?: {
    name: string;
    code: string;
    detail: string;
    recommendation: string;
  } | null;
};

export type OllamaToolSupportItem = {
  id: string;
  name: string;
  patterns: string[];
  examples: string[];
  support: "locally_verified" | "profile_available" | string;
  hardware: string;
  notes: string;
  profile: ToolProbeOptions;
};

export type OllamaToolSupportCatalog = {
  items: OllamaToolSupportItem[];
  known_limitations: Array<{
    patterns: string[];
    name: string;
    code: string;
    detail: string;
    recommendation: string;
  }>;
  custom_probe: {
    isolated_tool: string;
    executes_tool: boolean;
    stores_model_output: boolean;
    fields: Array<Record<string, unknown>>;
  };
  meaning: string;
};

export type Run = {
  run_id: string;
  batch_id: string;
  status: string;
  provider: string;
  model: string;
  split: string;
  seed: number;
  attempt: number;
  instance_id?: string;
  current_step?: number;
  current_tool?: string;
  authoritative_reward?: number | null;
  authoritative_verdict?: string;
  action_count?: number;
  model_call_count?: number;
  input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  cached_tokens?: number;
  estimated_cost?: number | null;
  elapsed_ms?: number;
  provider_latency_ms?: number;
  termination_reason?: string;
  truncation_reason?: string | null;
  environment_commit?: string;
  prompt_version?: string;
  record_digest?: string;
  failed_predicates?: string[];
  public_workload_outcomes?: Record<string, { outcome?: string }>;
  candidate_diff_summary?: {
    changed_paths: string[];
    file_count: number;
    retention?: {
      captured: boolean;
      artifact_digest: string | null;
      stored_bytes: number;
      redaction_count: number;
      truncated: boolean;
    };
  };
  candidate_diff_storage?: CandidateDiffStorage;
  candidate_diff?: CandidateDiffArtifact;
  authenticated_timeline?: TimelineEntry[];
  model_turn_debug?: ModelTurnDebug[];
  tool_use_debug?: ToolUseDebug | null;
  error_category?: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  ended_at?: string;
  limits?: {
    max_steps?: number;
    max_model_calls?: number;
    input_token_budget?: number | null;
    output_token_budget?: number | null;
    cost_budget?: number | null;
    wall_clock_seconds?: number;
  };
};

export type CandidateDiffStorage = {
  state: "available" | "deleted" | "not_captured" | "corrupt";
  stored_bytes: number;
  artifact_digest?: string | null;
};

export type CandidateDiffFile = {
  path: string;
  before_sha256: string;
  after_sha256: string;
  after_bytes: number;
  diff: string;
  truncated: boolean;
};

export type CandidateDiffArtifact = {
  artifact_version: string;
  artifact_digest: string;
  format: "unified_diff";
  files: CandidateDiffFile[];
  file_count: number;
  changed_paths: string[];
  redaction_count: number;
  truncated: boolean;
};

export type CandidateStorageSummary = {
  total_bytes: number;
  available_count: number;
  deleted_count: number;
  corrupt_count: number;
  items?: Array<CandidateDiffStorage & {
    run_id: string;
    provider: string;
    model: string;
    changed_paths: string[];
  }>;
};

export type TimelineEntry = {
  sequence: number;
  fake_tick?: number;
  tool: string;
  arguments: Record<string, unknown>;
  result_summary: unknown;
  request_bytes: number;
  response_bytes: number;
  duration_ms: number;
  success: boolean;
  error_code?: string | null;
  terminated: boolean;
  truncated: boolean;
  reward?: number | null;
};

export type ToolUseFinding = {
  severity: "error" | "warning";
  code: string;
  title: string;
  detail: string;
  remediation: string;
  sequence?: number | null;
  tool?: string | null;
};

export type ToolUseDebug = {
  summary: string;
  primary_cause: ToolUseFinding | null;
  findings: ToolUseFinding[];
  coverage: Record<string, number>;
  workflow_phases: Array<{
    id: string;
    title: string;
    status: "present" | "attempted" | "missing" | string;
    detail: string;
    tools_seen: string[];
  }>;
  protocol_health: {
    tool_calls_executed: number;
    tool_failures: number;
    model_calls: number;
    reasoning_tokens: number;
    protocol_issues: Array<{ code: string; title: string; detail: string }>;
    tool_calling_appears_functional: boolean;
  };
  expected_shortest_path: string[];
};

export type ModelTurnDebug = {
  turn: number;
  finish_reason?: string | null;
  tool_call_count: number;
  tool_names: string[];
  dropped_tool_calls: number;
  has_text: boolean;
  text_chars: number;
  has_reasoning: boolean;
  reasoning_chars: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  latency_ms: number;
};

export type Batch = {
  batch_id: string;
  status: string;
  provider: string;
  model: string;
  split: string;
  seed_start: number;
  seed_count: number;
  attempts: number;
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  cancelled_runs: number;
  running_runs: number;
  queued_runs: number;
  environment_commit: string;
  application_commit: string;
  created_at: string;
  aggregate_results: {
    strict_success_rate: number | null;
    average_reward: number | null;
    average_actions: number | null;
    estimated_total_cost: number | null;
    average_cost_per_success: number | null;
  };
  runs?: Run[];
};

export type ComparisonGroup = {
  batch_id: string;
  provider: string;
  model: string;
  environment_commit: string;
  run_count: number;
  strict_success_rate: number | null;
  average_reward: number | null;
  median_reward: number | null;
  average_actions: number | null;
  median_actions: number | null;
  average_token_usage: number | null;
  average_latency_ms: number | null;
  estimated_total_cost: number | null;
  cost_per_success: number | null;
  truncation_rate: number | null;
  provider_error_rate: number | null;
  consistency_across_attempts: number | null;
  failed_predicate_frequency: Record<string, number>;
  outcome_distribution: Record<string, number>;
  results_by_seed: Array<{ seed: number; attempt: number; reward: number; actions: number; input_tokens: number; output_tokens: number; tokens: number; latency_ms: number; cost: number | null }>;
};

export type TalonCapability = {
  capability_id: string;
  title: string;
  public_summary: string;
  safety_focus: string[];
};

export type TalonRecord = {
  record_id: string;
  kind: "dataset" | "training" | "evaluation";
  status: string;
  created_at: string;
  ended_at?: string;
  record_digest?: string;
  application_commit?: string;
  progress?: {
    phase?: string;
    epoch?: number;
    epochs?: number;
    loss?: number | null;
    training_action_accuracy?: number | null;
    completed_episodes?: number;
    total_episodes?: number;
  };
  dataset_digest?: string;
  trajectory_count?: number;
  architecture?: "gru" | "decision_transformer";
  parameter_count?: number;
  model_id?: string;
  checkpoint_digest?: string;
  training_metrics?: {
    loss: number;
    training_action_accuracy: number;
    validation_action_accuracy: number;
  };
  training_history?: { loss: number[]; training_action_accuracy: number[] };
  aggregate?: {
    episode_count: number;
    strict_success_count: number;
    strict_success_rate: number;
    safety_violation_count: number;
    safety_violation_rate: number;
    average_score: number;
    abstention_rate: number;
    false_escalation_rate: number;
    missed_threat_rate: number;
    expected_calibration_error: number;
    held_out_action_accuracy: number;
  };
  episodes?: TalonEpisode[];
  error_category?: string;
};

export type TalonEpisode = {
  schema_version: string;
  evaluation_id: string;
  checkpoint_digest: string;
  environment_version: string;
  verifier_version: string;
  result: {
    episode_id: string;
    score: number;
    strict_success: boolean;
    verdict: string;
    safety_violation_count: number;
    failed_categories: string[];
    action_count: number;
    result_digest: string;
    expected_calibration_error: number;
    confidence_calibration_bins: Array<{
      lower: number;
      upper: number;
      count: number;
      mean_confidence: number;
      gate_acceptance_rate: number;
    }>;
  };
  timeline: Array<{
    sequence: number;
    observation: Record<string, unknown>;
    recommendation: { recommended_action: string; action_confidence: number; uncertainty: number; reason_codes: string[] };
    gate: { accepted: boolean; requested_action: string; effective_action: string; violation_codes: string[]; human_approval_required: boolean; external_effect: boolean };
    public_reward: number;
    terminated: boolean;
    truncated: boolean;
  }>;
};
