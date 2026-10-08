-- Omneum local context graph.
--
-- PostgreSQL remains the authoritative relational store.
-- Apache AGE provides the graph representation used for traversal,
-- inspection, and future structural analysis.

BEGIN;

CREATE EXTENSION IF NOT EXISTS age;

LOAD 'age';

SET search_path = ag_catalog, "$user", public;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM ag_catalog.ag_graph
        WHERE name = 'omneum_context'
    ) THEN
        PERFORM ag_catalog.create_graph('omneum_context');
    END IF;
END
$$;

-- Context graph labels.
--
-- Source and Claim vertices reference their authoritative relational UUIDs.
-- OBSERVED represents an Observation: a Source supplied a Claim.
-- DEPENDENT represents symmetric estimated source dependence. AGE stores
-- directed edges, but Omneum treats this relationship as undirected.

-- ag_label.graph references ag_graph.graphid; check label kind explicitly.
DO $$
DECLARE
    label_name text;
    label_kind "char";
BEGIN
    FOR label_name, label_kind IN
        SELECT * FROM (VALUES ('Source', 'v'::"char"), ('Claim', 'v'::"char"),
                              ('OBSERVED', 'e'::"char"), ('DEPENDENT', 'e'::"char")) AS labels(name, kind)
    LOOP
        IF EXISTS (
            SELECT 1 FROM ag_catalog.ag_label l
            JOIN ag_catalog.ag_graph g ON g.graphid = l.graph
            WHERE g.name = 'omneum_context' AND l.name = label_name
              AND l.kind <> label_kind
        ) THEN
            RAISE EXCEPTION 'Unexpected kind for context graph label %', label_name;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM ag_catalog.ag_label l
            JOIN ag_catalog.ag_graph g ON g.graphid = l.graph
            WHERE g.name = 'omneum_context' AND l.name = label_name
        ) THEN
            IF label_kind = 'v' THEN
                PERFORM ag_catalog.create_vlabel('omneum_context', label_name::cstring);
            ELSE
                PERFORM ag_catalog.create_elabel('omneum_context', label_name::cstring);
            END IF;
        END IF;
    END LOOP;
END
$$;

-- Repair the bootstrap's workspace isolation without changing delete semantics.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.sources'::regclass
                   AND conname = 'sources_workspace_id_id_key') THEN
        ALTER TABLE public.sources ADD CONSTRAINT sources_workspace_id_id_key UNIQUE (workspace_id, id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.claims'::regclass
                   AND conname = 'claims_workspace_id_id_key') THEN
        ALTER TABLE public.claims ADD CONSTRAINT claims_workspace_id_id_key UNIQUE (workspace_id, id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.observations'::regclass
                   AND conname = 'observations_workspace_source_fkey') THEN
        ALTER TABLE public.observations ADD CONSTRAINT observations_workspace_source_fkey
            FOREIGN KEY (workspace_id, source_id) REFERENCES public.sources(workspace_id, id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.observations'::regclass
                   AND conname = 'observations_workspace_claim_fkey') THEN
        ALTER TABLE public.observations ADD CONSTRAINT observations_workspace_claim_fkey
            FOREIGN KEY (workspace_id, claim_id) REFERENCES public.claims(workspace_id, id);
    END IF;
END
$$;

COMMIT;
