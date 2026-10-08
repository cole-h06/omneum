-- Preserve extensible dependency signals and directional provenance evidence.
-- The aggregate dependency relationship remains symmetric; evidence may be directional.

BEGIN;

ALTER TABLE network.source_dependencies
    ADD COLUMN signal_components jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN evidence jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMIT;
