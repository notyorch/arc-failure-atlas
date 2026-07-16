export type FailureModeCount = {
  mode: string
  count: number
}

export type PilotSummary = {
  run_id: string
  experiment_id: string | null
  status: string | null
  solver_name: string | null
  solver_family: string | null
  model_name: string | null
  provider: string | null
  prompt_version: string | null
  base_url: string | null
  pack_id?: string | null
  benchmark_name?: string | null
  benchmark_version?: string | null
  n_tasks: number
  n_attempts: number
  solved_rate: number | null
  exact_match_rate: number | null
  avg_cell_accuracy: number | null
  avg_latency_ms: number | null
  total_cost_estimate_usd: number | null
  tokens_in: number | null
  tokens_out: number | null
  started_at: string | null
  finished_at: string | null
  dominant_failure_mode: string | null
  failure_modes: FailureModeCount[]
  comparison_scope: string
  artifact_path: string
}

export type PublicRow = {
  submission_name: string
  benchmark_name: string
  score: number | null
  score_percent: number | null
  trust_tier: string
  verification_status: string
  split_type: string
  comparison_scope: string
  cost_per_task_usd: number | null
  source_name: string
  local_run_id: string | null
  team_authors: string | null
}

export type TrustSummary = {
  trust_tier: string
  n: number
  mean_score: number | null
  max_score: number | null
}

export type ArtifactItem = {
  label: string
  path: string
  kind: string
  exists: boolean
}

export type OverviewData = {
  generated_at: string
  project: {
    name: string
    tagline: string
    mission: string
    what_it_is_not: string[]
  }
  pilot: PilotSummary | null
  public_context: {
    available: boolean
    n_rows?: number
    by_trust?: TrustSummary[]
    rows?: PublicRow[]
    message?: string
  }
  artifacts: ArtifactItem[]
}
