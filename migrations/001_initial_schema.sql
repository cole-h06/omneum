--
-- PostgreSQL database dump
--

\restrict 1HcgE130TPvWLBaiLuhOnWNouPbWXflfhYVyPg3pAvvkW1cYvoAjD2nrM2Dd04w

-- Dumped from database version 15.18 (Homebrew)
-- Dumped by pg_dump version 15.18 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--



--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: evaluation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.evaluation_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed'
);


--
-- Name: visibility_scope; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.visibility_scope AS ENUM (
    'private',
    'organization',
    'public'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    name text NOT NULL,
    external_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    name text NOT NULL,
    key_prefix text NOT NULL,
    key_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone
);


--
-- Name: claim_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claim_scores (
    evaluation_run_id uuid NOT NULL,
    claim_id uuid NOT NULL,
    support_score double precision NOT NULL,
    effective_independent_support double precision,
    dependency_cluster_count integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claims (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    claim_token bytea NOT NULL,
    public_value jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: evaluation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    algorithm text DEFAULT 'BRAID'::text NOT NULL,
    algorithm_version text NOT NULL,
    status public.evaluation_status DEFAULT 'pending'::public.evaluation_status NOT NULL,
    parameters jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.observations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    agent_id uuid,
    source_id uuid NOT NULL,
    claim_id uuid NOT NULL,
    observation_type text DEFAULT 'assertion'::text NOT NULL,
    visibility public.visibility_scope DEFAULT 'private'::public.visibility_scope NOT NULL,
    observed_at timestamp with time zone DEFAULT now() NOT NULL,
    source_modified_at timestamp with time zone,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    evaluation_run_id uuid,
    name text,
    observation_cutoff timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: source_dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_dependencies (
    evaluation_run_id uuid NOT NULL,
    source_a_id uuid NOT NULL,
    source_b_id uuid NOT NULL,
    dependency_score double precision NOT NULL,
    signal_coverage double precision,
    components jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT source_dependencies_check CHECK ((source_a_id <> source_b_id)),
    CONSTRAINT source_dependencies_dependency_score_check CHECK (((dependency_score >= (0)::double precision) AND (dependency_score <= (1)::double precision))),
    CONSTRAINT source_dependencies_signal_coverage_check CHECK (((signal_coverage >= (0)::double precision) AND (signal_coverage <= (1)::double precision)))
);


--
-- Name: source_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_scores (
    evaluation_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    reliability_score double precision NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workspace_id uuid NOT NULL,
    source_token bytea NOT NULL,
    source_kind text,
    public_identifier text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: agents agents_workspace_id_external_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_workspace_id_external_id_key UNIQUE (workspace_id, external_id);


--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: claim_scores claim_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_scores
    ADD CONSTRAINT claim_scores_pkey PRIMARY KEY (evaluation_run_id, claim_id);


--
-- Name: claims claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_pkey PRIMARY KEY (id);


--
-- Name: claims claims_workspace_id_claim_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_workspace_id_claim_token_key UNIQUE (workspace_id, claim_token);


--
-- Name: evaluation_runs evaluation_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_runs
    ADD CONSTRAINT evaluation_runs_pkey PRIMARY KEY (id);


--
-- Name: observations observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: snapshots snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_pkey PRIMARY KEY (id);


--
-- Name: source_dependencies source_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_dependencies
    ADD CONSTRAINT source_dependencies_pkey PRIMARY KEY (evaluation_run_id, source_a_id, source_b_id);


--
-- Name: source_scores source_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_scores
    ADD CONSTRAINT source_scores_pkey PRIMARY KEY (evaluation_run_id, source_id);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);


--
-- Name: sources sources_workspace_id_source_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_workspace_id_source_token_key UNIQUE (workspace_id, source_token);


--
-- Name: workspaces workspaces_organization_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_organization_id_name_key UNIQUE (organization_id, name);


--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);


--
-- Name: evaluation_runs_workspace_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evaluation_runs_workspace_time_idx ON public.evaluation_runs USING btree (workspace_id, created_at DESC);


--
-- Name: observations_claim_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX observations_claim_idx ON public.observations USING btree (claim_id);


--
-- Name: observations_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX observations_source_idx ON public.observations USING btree (source_id);


--
-- Name: observations_workspace_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX observations_workspace_time_idx ON public.observations USING btree (workspace_id, observed_at DESC);


--
-- Name: agents agents_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: api_keys api_keys_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: claim_scores claim_scores_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_scores
    ADD CONSTRAINT claim_scores_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id);


--
-- Name: claim_scores claim_scores_evaluation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claim_scores
    ADD CONSTRAINT claim_scores_evaluation_run_id_fkey FOREIGN KEY (evaluation_run_id) REFERENCES public.evaluation_runs(id) ON DELETE CASCADE;


--
-- Name: claims claims_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: evaluation_runs evaluation_runs_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_runs
    ADD CONSTRAINT evaluation_runs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: observations observations_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: observations observations_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id);


--
-- Name: observations observations_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: observations observations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: snapshots snapshots_evaluation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_evaluation_run_id_fkey FOREIGN KEY (evaluation_run_id) REFERENCES public.evaluation_runs(id) ON DELETE SET NULL;


--
-- Name: snapshots snapshots_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: source_dependencies source_dependencies_evaluation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_dependencies
    ADD CONSTRAINT source_dependencies_evaluation_run_id_fkey FOREIGN KEY (evaluation_run_id) REFERENCES public.evaluation_runs(id) ON DELETE CASCADE;


--
-- Name: source_dependencies source_dependencies_source_a_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_dependencies
    ADD CONSTRAINT source_dependencies_source_a_id_fkey FOREIGN KEY (source_a_id) REFERENCES public.sources(id);


--
-- Name: source_dependencies source_dependencies_source_b_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_dependencies
    ADD CONSTRAINT source_dependencies_source_b_id_fkey FOREIGN KEY (source_b_id) REFERENCES public.sources(id);


--
-- Name: source_scores source_scores_evaluation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_scores
    ADD CONSTRAINT source_scores_evaluation_run_id_fkey FOREIGN KEY (evaluation_run_id) REFERENCES public.evaluation_runs(id) ON DELETE CASCADE;


--
-- Name: source_scores source_scores_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_scores
    ADD CONSTRAINT source_scores_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: sources sources_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspaces workspaces_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict 1HcgE130TPvWLBaiLuhOnWNouPbWXflfhYVyPg3pAvvkW1cYvoAjD2nrM2Dd04w

