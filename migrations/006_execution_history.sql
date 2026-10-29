BEGIN;
CREATE TABLE IF NOT EXISTS public.execution_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    evaluation_run_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    sdk_end_to_end_latency_ms double precision CHECK (sdk_end_to_end_latency_ms >= 0),
    evaluation_latency_ms double precision CHECK (evaluation_latency_ms >= 0),
    graph_evaluation_latency_ms double precision CHECK (graph_evaluation_latency_ms >= 0),
    mcp_roundtrip_latency_ms double precision CHECK (mcp_roundtrip_latency_ms >= 0),
    chunk_selection_latency_ms double precision CHECK (chunk_selection_latency_ms >= 0),
    context_reconstruction_latency_ms double precision CHECK (context_reconstruction_latency_ms >= 0),
    local_inference_latency_ms double precision CHECK (local_inference_latency_ms >= 0),
    cpu_time_ms double precision CHECK (cpu_time_ms >= 0),
    peak_memory_bytes bigint CHECK (peak_memory_bytes >= 0),
    input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
    selected_tokens bigint NOT NULL CHECK (selected_tokens >= 0),
    token_budget bigint NOT NULL CHECK (token_budget >= 0 AND selected_tokens <= token_budget),
    reduction_ratio double precision,
    cpu_time_scope text NOT NULL,
    peak_memory_scope text NOT NULL,
    UNIQUE (workspace_id, evaluation_run_id),
    FOREIGN KEY (workspace_id, evaluation_run_id)
        REFERENCES public.evaluation_runs (workspace_id, id) ON DELETE CASCADE
);
COMMIT;
