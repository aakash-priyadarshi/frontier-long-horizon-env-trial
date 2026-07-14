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
    source: "not_required" | "missing" | "environment" | "session" | "os_vault";
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
};

export type ProviderModel = {
  id: string;
  display_name: string;
  size?: number;
  digest?: string;
  details?: { family?: string; parameter_size?: string; quantization_level?: string };
  tool_compatibility?: ToolCompatibility;
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
  candidate_diff_summary?: { changed_paths: string[]; file_count: number };
  authenticated_timeline?: TimelineEntry[];
  error_category?: string | null;
  limits?: {
    max_steps?: number;
    max_model_calls?: number;
    input_token_budget?: number | null;
    output_token_budget?: number | null;
    cost_budget?: number | null;
    wall_clock_seconds?: number;
  };
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
