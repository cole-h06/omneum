-- Workspace isolation and symmetric pair identity for evaluation history.
-- Existing inconsistent rows fail validation; no results are discarded/reordered.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.evaluation_runs'::regclass
                     AND conname = 'evaluation_runs_workspace_id_id_key') THEN
        ALTER TABLE public.evaluation_runs
            ADD CONSTRAINT evaluation_runs_workspace_id_id_key UNIQUE (workspace_id, id);
    END IF;
END
$$;

ALTER TABLE public.source_scores ADD COLUMN IF NOT EXISTS workspace_id uuid;
ALTER TABLE public.claim_scores ADD COLUMN IF NOT EXISTS workspace_id uuid;
ALTER TABLE public.source_dependencies ADD COLUMN IF NOT EXISTS workspace_id uuid;

UPDATE public.source_scores s SET workspace_id = r.workspace_id
FROM public.evaluation_runs r WHERE s.evaluation_run_id = r.id AND s.workspace_id IS NULL;
UPDATE public.claim_scores s SET workspace_id = r.workspace_id
FROM public.evaluation_runs r WHERE s.evaluation_run_id = r.id AND s.workspace_id IS NULL;
UPDATE public.source_dependencies s SET workspace_id = r.workspace_id
FROM public.evaluation_runs r WHERE s.evaluation_run_id = r.id AND s.workspace_id IS NULL;

ALTER TABLE public.source_scores ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.claim_scores ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.source_dependencies ALTER COLUMN workspace_id SET NOT NULL;

DO $$
DECLARE
    item record;
BEGIN
    -- SQL definitions below are migration constants, never application data.
    FOR item IN SELECT * FROM (VALUES
        ('source_scores', 'source_scores_workspace_run_fkey',
         'FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES public.evaluation_runs(workspace_id, id) ON DELETE CASCADE'),
        ('source_scores', 'source_scores_workspace_source_fkey',
         'FOREIGN KEY (workspace_id, source_id) REFERENCES public.sources(workspace_id, id)'),
        ('claim_scores', 'claim_scores_workspace_run_fkey',
         'FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES public.evaluation_runs(workspace_id, id) ON DELETE CASCADE'),
        ('claim_scores', 'claim_scores_workspace_claim_fkey',
         'FOREIGN KEY (workspace_id, claim_id) REFERENCES public.claims(workspace_id, id)'),
        ('source_dependencies', 'source_dependencies_workspace_run_fkey',
         'FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES public.evaluation_runs(workspace_id, id) ON DELETE CASCADE'),
        ('source_dependencies', 'source_dependencies_workspace_a_fkey',
         'FOREIGN KEY (workspace_id, source_a_id) REFERENCES public.sources(workspace_id, id)'),
        ('source_dependencies', 'source_dependencies_workspace_b_fkey',
         'FOREIGN KEY (workspace_id, source_b_id) REFERENCES public.sources(workspace_id, id)'),
        ('source_dependencies', 'source_dependencies_canonical_pair_check',
         'CHECK (source_a_id < source_b_id)')
    ) AS constraints(table_name, constraint_name, definition)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = format('public.%I', item.table_name)::regclass
              AND conname = item.constraint_name
        ) THEN
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s',
                           item.table_name, item.constraint_name, item.definition);
        END IF;
    END LOOP;
END
$$;

COMMIT;
