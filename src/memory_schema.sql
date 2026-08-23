BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopping_memory_owner') THEN
        CREATE ROLE shopping_memory_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopping_memory_migrator') THEN
        CREATE ROLE shopping_memory_migrator NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopping_memory_api') THEN
        CREATE ROLE shopping_memory_api NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopping_memory_worker') THEN
        CREATE ROLE shopping_memory_worker NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopping_memory_poller') THEN
        CREATE ROLE shopping_memory_poller NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopping_memory_maintenance') THEN
        CREATE ROLE shopping_memory_maintenance NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$roles$;

ALTER ROLE shopping_memory_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
ALTER ROLE shopping_memory_migrator NOLOGIN NOSUPERUSER NOBYPASSRLS;
ALTER ROLE shopping_memory_api NOLOGIN NOSUPERUSER NOBYPASSRLS;
ALTER ROLE shopping_memory_worker NOLOGIN NOSUPERUSER NOBYPASSRLS;
ALTER ROLE shopping_memory_poller NOLOGIN NOSUPERUSER NOBYPASSRLS;
ALTER ROLE shopping_memory_maintenance NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT shopping_memory_owner TO shopping_memory_migrator;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS memory AUTHORIZATION shopping_memory_owner;
ALTER SCHEMA memory OWNER TO shopping_memory_owner;
SET LOCAL ROLE shopping_memory_owner;
SET LOCAL search_path = memory, public, pg_catalog;

CREATE TABLE IF NOT EXISTS memory.assistant_threads (
    tenant_id uuid NOT NULL,
    thread_id uuid NOT NULL,
    user_id uuid NOT NULL,
    conversation_state jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_intent text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, thread_id),
    CHECK (jsonb_typeof(conversation_state) = 'object'),
    CHECK (last_intent IS NULL OR last_intent IN (
        'single_item_recommend', 'outfit_analyze', 'outfit_revise',
        'scene_outfit_generate', 'unsupported'
    )),
    CHECK (expires_at >= updated_at)
);

CREATE TABLE IF NOT EXISTS memory.procedural_prompt_versions (
    tenant_id uuid NOT NULL,
    prompt_key text NOT NULL,
    version_id uuid NOT NULL,
    parent_version_id uuid,
    content text NOT NULL,
    content_hash bytea NOT NULL,
    status text NOT NULL,
    evidence_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    evaluation_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid NOT NULL,
    approved_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    PRIMARY KEY (tenant_id, prompt_key, version_id),
    FOREIGN KEY (tenant_id, prompt_key, parent_version_id)
        REFERENCES memory.procedural_prompt_versions
            (tenant_id, prompt_key, version_id)
        ON DELETE RESTRICT,
    UNIQUE (tenant_id, prompt_key, content_hash),
    CHECK (btrim(prompt_key) <> ''),
    CHECK (btrim(content) <> ''),
    CHECK (octet_length(content_hash) = 32),
    CHECK (status IN ('draft', 'review', 'approved', 'rejected')),
    CHECK (jsonb_typeof(evidence_summary) = 'object'),
    CHECK (jsonb_typeof(evaluation_metrics) = 'object'),
    CHECK (
        (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR
        (status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS memory.procedural_prompt_active (
    tenant_id uuid NOT NULL,
    prompt_key text NOT NULL,
    version_id uuid NOT NULL,
    generation bigint NOT NULL DEFAULT 1,
    activated_by uuid NOT NULL,
    activated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, prompt_key),
    FOREIGN KEY (tenant_id, prompt_key, version_id)
        REFERENCES memory.procedural_prompt_versions
            (tenant_id, prompt_key, version_id)
        ON DELETE RESTRICT,
    CHECK (generation > 0)
);

CREATE TABLE IF NOT EXISTS memory.assistant_runs (
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    thread_id uuid NOT NULL,
    intent text NOT NULL,
    status text NOT NULL,
    request_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    prompt_key text,
    prompt_version_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, run_id),
    FOREIGN KEY (tenant_id, thread_id)
        REFERENCES memory.assistant_threads (tenant_id, thread_id)
        ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, prompt_key, prompt_version_id)
        REFERENCES memory.procedural_prompt_versions
            (tenant_id, prompt_key, version_id)
        ON DELETE RESTRICT,
    CHECK (intent IN (
        'single_item_recommend', 'outfit_analyze', 'outfit_revise',
        'scene_outfit_generate', 'unsupported'
    )),
    CHECK (status IN ('ok', 'not_ready', 'unsupported', 'error')),
    CHECK (jsonb_typeof(request_summary) = 'object'),
    CHECK (jsonb_typeof(response_summary) = 'object'),
    CHECK ((prompt_key IS NULL) = (prompt_version_id IS NULL)),
    CHECK (prompt_key IS NULL OR btrim(prompt_key) <> ''),
    CHECK (expires_at >= created_at)
);

CREATE TABLE IF NOT EXISTS memory.assistant_feedback (
    tenant_id uuid NOT NULL,
    feedback_id uuid NOT NULL,
    run_id uuid NOT NULL,
    event text NOT NULL,
    rating smallint,
    comment text,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, feedback_id),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES memory.assistant_runs (tenant_id, run_id)
        ON DELETE CASCADE,
    UNIQUE (tenant_id, run_id, idempotency_key),
    CHECK (event IN (
        'accepted', 'saved', 'purchased', 'thumbs_up', 'thumbs_down', 'rating'
    )),
    CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    CHECK (event <> 'rating' OR rating IS NOT NULL),
    CHECK (btrim(idempotency_key) <> ''),
    CHECK (expires_at >= created_at)
);

CREATE TABLE IF NOT EXISTS memory.semantic_memories (
    tenant_id uuid NOT NULL,
    memory_id uuid NOT NULL,
    user_id uuid NOT NULL,
    dimension text NOT NULL,
    value text NOT NULL,
    polarity smallint NOT NULL,
    context text,
    confidence real NOT NULL,
    source_run_id uuid,
    embedding public.vector(1024),
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    deleted_at timestamptz,
    PRIMARY KEY (tenant_id, memory_id),
    FOREIGN KEY (tenant_id, source_run_id)
        REFERENCES memory.assistant_runs (tenant_id, run_id)
        ON DELETE SET NULL (source_run_id),
    CHECK (dimension IN ('color', 'style', 'category', 'scene', 'constraint')),
    CHECK (btrim(value) <> ''),
    CHECK (polarity IN (-1, 1)),
    CHECK (confidence BETWEEN 0 AND 1),
    CHECK (status IN ('active', 'superseded', 'deleted')),
    CHECK (
        (status = 'deleted' AND deleted_at IS NOT NULL AND embedding IS NULL)
        OR
        (status <> 'deleted' AND deleted_at IS NULL AND embedding IS NOT NULL)
    ),
    CHECK (expires_at IS NULL OR expires_at >= created_at)
);

CREATE TABLE IF NOT EXISTS memory.episodic_memories (
    tenant_id uuid NOT NULL,
    memory_id uuid NOT NULL,
    owner_user_id uuid,
    scope text NOT NULL,
    observation text NOT NULL,
    action text NOT NULL,
    result text NOT NULL,
    source_run_id uuid,
    source_feedback_id uuid,
    embedding public.vector(1024),
    status text NOT NULL,
    reviewed_by uuid,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    deleted_at timestamptz,
    PRIMARY KEY (tenant_id, memory_id),
    FOREIGN KEY (tenant_id, source_run_id)
        REFERENCES memory.assistant_runs (tenant_id, run_id)
        ON DELETE SET NULL (source_run_id),
    FOREIGN KEY (tenant_id, source_feedback_id)
        REFERENCES memory.assistant_feedback (tenant_id, feedback_id)
        ON DELETE SET NULL (source_feedback_id),
    CHECK (scope IN ('user', 'tenant')),
    CHECK ((scope = 'user') = (owner_user_id IS NOT NULL)),
    CHECK (btrim(observation) <> '' AND btrim(action) <> '' AND btrim(result) <> ''),
    CHECK (status IN ('pending', 'active', 'rejected', 'deleted')),
    CHECK (
        scope <> 'tenant'
        OR status NOT IN ('active', 'rejected')
        OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
    ),
    CHECK (
        (status = 'deleted' AND deleted_at IS NOT NULL AND embedding IS NULL)
        OR
        (status <> 'deleted' AND deleted_at IS NULL AND embedding IS NOT NULL)
    ),
    CHECK (expires_at >= created_at)
);

CREATE TABLE IF NOT EXISTS memory.memory_jobs (
    tenant_id uuid NOT NULL,
    job_id uuid NOT NULL,
    user_id uuid,
    job_type text NOT NULL,
    source_run_id uuid,
    dedupe_key text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending',
    attempts smallint NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz,
    locked_by uuid,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY (tenant_id, source_run_id)
        REFERENCES memory.assistant_runs (tenant_id, run_id)
        ON DELETE SET NULL (source_run_id),
    UNIQUE (tenant_id, job_type, dedupe_key),
    CHECK (job_type IN ('semantic_extract', 'episodic_extract', 'procedural_optimize')),
    CHECK (btrim(dedupe_key) <> ''),
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (status IN ('pending', 'running', 'done', 'failed')),
    CHECK (attempts >= 0),
    CHECK (
        (status = 'running' AND locked_at IS NOT NULL AND locked_by IS NOT NULL)
        OR
        (status <> 'running' AND locked_at IS NULL AND locked_by IS NULL)
    ),
    CHECK (expires_at >= created_at)
);

CREATE TABLE IF NOT EXISTS memory.audit_events (
    tenant_id uuid NOT NULL,
    event_id uuid NOT NULL,
    actor_user_id uuid,
    actor_type text NOT NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CHECK (actor_type IN ('user', 'worker', 'system')),
    CHECK (actor_type <> 'user' OR actor_user_id IS NOT NULL),
    CHECK (btrim(action) <> ''),
    CHECK (btrim(resource_type) <> ''),
    CHECK (btrim(resource_id) <> ''),
    CHECK (jsonb_typeof(details) = 'object'),
    CHECK (expires_at >= created_at)
);

CREATE INDEX IF NOT EXISTS assistant_threads_user_updated_idx
    ON memory.assistant_threads (tenant_id, user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS assistant_threads_expires_idx
    ON memory.assistant_threads (expires_at);
CREATE INDEX IF NOT EXISTS prompt_versions_created_idx
    ON memory.procedural_prompt_versions (tenant_id, prompt_key, created_at DESC);
CREATE INDEX IF NOT EXISTS assistant_runs_thread_created_idx
    ON memory.assistant_runs (tenant_id, thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS assistant_runs_expires_idx
    ON memory.assistant_runs (expires_at);
CREATE INDEX IF NOT EXISTS feedback_run_created_idx
    ON memory.assistant_feedback (tenant_id, run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS feedback_expires_idx
    ON memory.assistant_feedback (expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS semantic_active_dedupe_idx
    ON memory.semantic_memories
        (tenant_id, user_id, dimension, lower(value), polarity)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS semantic_owner_status_idx
    ON memory.semantic_memories (tenant_id, user_id, status);
CREATE INDEX IF NOT EXISTS semantic_expires_idx
    ON memory.semantic_memories (expires_at)
    WHERE expires_at IS NOT NULL AND status = 'active';
CREATE INDEX IF NOT EXISTS semantic_deleted_idx
    ON memory.semantic_memories (deleted_at)
    WHERE status = 'deleted';
CREATE INDEX IF NOT EXISTS episodic_owner_status_idx
    ON memory.episodic_memories (tenant_id, owner_user_id, status);
CREATE INDEX IF NOT EXISTS episodic_shared_status_idx
    ON memory.episodic_memories (tenant_id, status)
    WHERE scope = 'tenant';
CREATE INDEX IF NOT EXISTS episodic_expires_idx
    ON memory.episodic_memories (expires_at)
    WHERE status IN ('pending', 'active');
CREATE INDEX IF NOT EXISTS episodic_deleted_idx
    ON memory.episodic_memories (deleted_at)
    WHERE status = 'deleted';
CREATE INDEX IF NOT EXISTS memory_jobs_claim_idx
    ON memory.memory_jobs (available_at, created_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS memory_jobs_tenant_status_idx
    ON memory.memory_jobs (tenant_id, status, updated_at);
CREATE INDEX IF NOT EXISTS memory_jobs_expires_idx
    ON memory.memory_jobs (expires_at)
    WHERE status IN ('done', 'failed');
CREATE INDEX IF NOT EXISTS audit_tenant_created_idx
    ON memory.audit_events (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_resource_created_idx
    ON memory.audit_events
        (tenant_id, resource_type, resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_expires_idx
    ON memory.audit_events (expires_at);

CREATE OR REPLACE FUNCTION memory.current_tenant_id()
RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION memory.current_user_id()
RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION memory.current_app_role()
RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT coalesce(nullif(current_setting('app.role', true), ''), '')
$$;

CREATE OR REPLACE FUNCTION memory.current_worker_id()
RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT nullif(current_setting('app.worker_id', true), '')::uuid
$$;

ALTER TABLE memory.assistant_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.assistant_threads FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.assistant_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.assistant_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.semantic_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.semantic_memories FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.assistant_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.assistant_feedback FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.episodic_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.episodic_memories FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.procedural_prompt_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.procedural_prompt_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.procedural_prompt_active ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.procedural_prompt_active FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.memory_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.memory_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE memory.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory.audit_events FORCE ROW LEVEL SECURITY;

DO $owner_policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'assistant_threads', 'assistant_runs', 'semantic_memories',
        'assistant_feedback', 'episodic_memories',
        'procedural_prompt_versions', 'procedural_prompt_active',
        'memory_jobs', 'audit_events'
    ]
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS memory_owner_all ON memory.%I', table_name
        );
        EXECUTE format(
            'CREATE POLICY memory_owner_all ON memory.%I FOR ALL '
            'TO shopping_memory_owner USING (true) WITH CHECK (true)',
            table_name
        );
    END LOOP;
END
$owner_policies$;

DROP POLICY IF EXISTS threads_api_all ON memory.assistant_threads;
CREATE POLICY threads_api_all ON memory.assistant_threads
FOR ALL TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
);

DROP POLICY IF EXISTS threads_worker_select ON memory.assistant_threads;
CREATE POLICY threads_worker_select ON memory.assistant_threads
FOR SELECT TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
    AND memory.current_app_role() = 'worker'
);

DROP POLICY IF EXISTS runs_api_select ON memory.assistant_runs;
CREATE POLICY runs_api_select ON memory.assistant_runs
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND EXISTS (
        SELECT 1 FROM memory.assistant_threads thread
        WHERE thread.tenant_id = assistant_runs.tenant_id
          AND thread.thread_id = assistant_runs.thread_id
          AND thread.user_id = memory.current_user_id()
    )
);

DROP POLICY IF EXISTS runs_api_insert ON memory.assistant_runs;
CREATE POLICY runs_api_insert ON memory.assistant_runs
FOR INSERT TO shopping_memory_api
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND EXISTS (
        SELECT 1 FROM memory.assistant_threads thread
        WHERE thread.tenant_id = assistant_runs.tenant_id
          AND thread.thread_id = assistant_runs.thread_id
          AND thread.user_id = memory.current_user_id()
    )
);

DROP POLICY IF EXISTS runs_worker_select ON memory.assistant_runs;
CREATE POLICY runs_worker_select ON memory.assistant_runs
FOR SELECT TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND EXISTS (
        SELECT 1 FROM memory.assistant_threads thread
        WHERE thread.tenant_id = assistant_runs.tenant_id
          AND thread.thread_id = assistant_runs.thread_id
          AND thread.user_id = memory.current_user_id()
    )
);

DROP POLICY IF EXISTS semantic_api_select ON memory.semantic_memories;
CREATE POLICY semantic_api_select ON memory.semantic_memories
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
);

DROP POLICY IF EXISTS semantic_api_update ON memory.semantic_memories;
CREATE POLICY semantic_api_update ON memory.semantic_memories
FOR UPDATE TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
);

DROP POLICY IF EXISTS semantic_worker_all ON memory.semantic_memories;
CREATE POLICY semantic_worker_all ON memory.semantic_memories
FOR ALL TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
    AND memory.current_app_role() = 'worker'
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND user_id = memory.current_user_id()
    AND memory.current_app_role() = 'worker'
);

DROP POLICY IF EXISTS feedback_api_select ON memory.assistant_feedback;
CREATE POLICY feedback_api_select ON memory.assistant_feedback
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND EXISTS (
        SELECT 1
        FROM memory.assistant_runs run
        JOIN memory.assistant_threads thread
          ON thread.tenant_id = run.tenant_id
         AND thread.thread_id = run.thread_id
        WHERE run.tenant_id = assistant_feedback.tenant_id
          AND run.run_id = assistant_feedback.run_id
          AND thread.user_id = memory.current_user_id()
    )
);

DROP POLICY IF EXISTS feedback_api_insert ON memory.assistant_feedback;
CREATE POLICY feedback_api_insert ON memory.assistant_feedback
FOR INSERT TO shopping_memory_api
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND EXISTS (
        SELECT 1
        FROM memory.assistant_runs run
        JOIN memory.assistant_threads thread
          ON thread.tenant_id = run.tenant_id
         AND thread.thread_id = run.thread_id
        WHERE run.tenant_id = assistant_feedback.tenant_id
          AND run.run_id = assistant_feedback.run_id
          AND thread.user_id = memory.current_user_id()
    )
);

DROP POLICY IF EXISTS feedback_worker_select ON memory.assistant_feedback;
CREATE POLICY feedback_worker_select ON memory.assistant_feedback
FOR SELECT TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND EXISTS (
        SELECT 1
        FROM memory.assistant_runs run
        JOIN memory.assistant_threads thread
          ON thread.tenant_id = run.tenant_id
         AND thread.thread_id = run.thread_id
        WHERE run.tenant_id = assistant_feedback.tenant_id
          AND run.run_id = assistant_feedback.run_id
          AND thread.user_id = memory.current_user_id()
    )
);

DROP POLICY IF EXISTS episodic_api_select ON memory.episodic_memories;
CREATE POLICY episodic_api_select ON memory.episodic_memories
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND (
        (
            memory.current_app_role() = 'user'
            AND scope = 'user'
            AND owner_user_id = memory.current_user_id()
        )
        OR (scope = 'tenant' AND status = 'active')
        OR (scope = 'tenant' AND memory.current_app_role() = 'tenant_admin')
    )
);

DROP POLICY IF EXISTS episodic_api_update ON memory.episodic_memories;
CREATE POLICY episodic_api_update ON memory.episodic_memories
FOR UPDATE TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND (
        (
            memory.current_app_role() = 'user'
            AND scope = 'user'
            AND owner_user_id = memory.current_user_id()
        )
        OR (
            scope = 'tenant'
            AND status = 'pending'
            AND memory.current_app_role() = 'tenant_admin'
        )
    )
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND (
        (
            memory.current_app_role() = 'user'
            AND scope = 'user'
            AND owner_user_id = memory.current_user_id()
        )
        OR (
            scope = 'tenant'
            AND status IN ('active', 'rejected')
            AND memory.current_app_role() = 'tenant_admin'
        )
    )
);

DROP POLICY IF EXISTS episodic_worker_all ON memory.episodic_memories;
CREATE POLICY episodic_worker_all ON memory.episodic_memories
FOR ALL TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND (
        (scope = 'user' AND owner_user_id = memory.current_user_id())
        OR (
            scope = 'tenant'
            AND status = 'pending'
            AND memory.current_user_id() IS NULL
        )
    )
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND (
        (scope = 'user' AND owner_user_id = memory.current_user_id())
        OR (
            scope = 'tenant'
            AND status = 'pending'
            AND memory.current_user_id() IS NULL
        )
    )
);

DROP POLICY IF EXISTS prompt_versions_api_select ON memory.procedural_prompt_versions;
CREATE POLICY prompt_versions_api_select ON memory.procedural_prompt_versions
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND (
        memory.current_app_role() = 'tenant_admin'
        OR EXISTS (
            SELECT 1 FROM memory.procedural_prompt_active active
            WHERE active.tenant_id = procedural_prompt_versions.tenant_id
              AND active.prompt_key = procedural_prompt_versions.prompt_key
              AND active.version_id = procedural_prompt_versions.version_id
        )
    )
);

DROP POLICY IF EXISTS prompt_versions_api_insert ON memory.procedural_prompt_versions;
CREATE POLICY prompt_versions_api_insert ON memory.procedural_prompt_versions
FOR INSERT TO shopping_memory_api
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'tenant_admin'
);

DROP POLICY IF EXISTS prompt_versions_api_update ON memory.procedural_prompt_versions;
CREATE POLICY prompt_versions_api_update ON memory.procedural_prompt_versions
FOR UPDATE TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'tenant_admin'
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'tenant_admin'
);

DROP POLICY IF EXISTS prompt_versions_worker_insert ON memory.procedural_prompt_versions;
CREATE POLICY prompt_versions_worker_insert ON memory.procedural_prompt_versions
FOR INSERT TO shopping_memory_worker
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND status = 'draft'
);

DROP POLICY IF EXISTS prompt_active_api_select ON memory.procedural_prompt_active;
CREATE POLICY prompt_active_api_select ON memory.procedural_prompt_active
FOR SELECT TO shopping_memory_api
USING (tenant_id = memory.current_tenant_id());

DROP POLICY IF EXISTS prompt_active_worker_select ON memory.procedural_prompt_active;
CREATE POLICY prompt_active_worker_select ON memory.procedural_prompt_active
FOR SELECT TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
);

DROP POLICY IF EXISTS jobs_api_select ON memory.memory_jobs;
CREATE POLICY jobs_api_select ON memory.memory_jobs
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND (
        user_id = memory.current_user_id()
        OR (user_id IS NULL AND memory.current_app_role() = 'tenant_admin')
    )
);

DROP POLICY IF EXISTS jobs_api_insert ON memory.memory_jobs;
CREATE POLICY jobs_api_insert ON memory.memory_jobs
FOR INSERT TO shopping_memory_api
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND (
        user_id = memory.current_user_id()
        OR (
            user_id IS NULL
            AND job_type IN ('episodic_extract', 'procedural_optimize')
            AND memory.current_app_role() = 'tenant_admin'
        )
    )
);

DROP POLICY IF EXISTS jobs_worker_select ON memory.memory_jobs;
CREATE POLICY jobs_worker_select ON memory.memory_jobs
FOR SELECT TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND status = 'running'
    AND locked_by = memory.current_worker_id()
    AND (user_id = memory.current_user_id() OR (user_id IS NULL AND memory.current_user_id() IS NULL))
);

DROP POLICY IF EXISTS jobs_worker_update ON memory.memory_jobs;
CREATE POLICY jobs_worker_update ON memory.memory_jobs
FOR UPDATE TO shopping_memory_worker
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND status = 'running'
    AND locked_by = memory.current_worker_id()
)
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'worker'
    AND (
        (status = 'running' AND locked_by = memory.current_worker_id() AND locked_at IS NOT NULL)
        OR (status IN ('done', 'failed') AND locked_by IS NULL AND locked_at IS NULL)
    )
);

DROP POLICY IF EXISTS audit_api_select ON memory.audit_events;
CREATE POLICY audit_api_select ON memory.audit_events
FOR SELECT TO shopping_memory_api
USING (
    tenant_id = memory.current_tenant_id()
    AND memory.current_app_role() = 'tenant_admin'
);

DROP POLICY IF EXISTS audit_api_insert ON memory.audit_events;
CREATE POLICY audit_api_insert ON memory.audit_events
FOR INSERT TO shopping_memory_api
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND actor_type = 'user'
    AND actor_user_id = memory.current_user_id()
);

DROP POLICY IF EXISTS audit_worker_insert ON memory.audit_events;
CREATE POLICY audit_worker_insert ON memory.audit_events
FOR INSERT TO shopping_memory_worker
WITH CHECK (
    tenant_id = memory.current_tenant_id()
    AND actor_type = 'worker'
    AND memory.current_app_role() = 'worker'
);

CREATE OR REPLACE FUNCTION memory.claim_memory_job(
    p_worker_id uuid
)
RETURNS TABLE (
    tenant_id uuid,
    job_id uuid,
    user_id uuid,
    job_type text,
    source_run_id uuid,
    payload jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
BEGIN
    RETURN QUERY
    WITH candidate AS (
        SELECT job.tenant_id, job.job_id
        FROM memory.memory_jobs job
        WHERE job.status = 'pending'
          AND job.available_at <= now()
        ORDER BY job.available_at, job.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE memory.memory_jobs job
    SET status = 'running',
        attempts = job.attempts + 1,
        locked_at = now(),
        locked_by = p_worker_id,
        updated_at = now()
    FROM candidate
    WHERE job.tenant_id = candidate.tenant_id
      AND job.job_id = candidate.job_id
    RETURNING job.tenant_id, job.job_id, job.user_id, job.job_type,
              job.source_run_id, job.payload;
END
$$;

CREATE OR REPLACE FUNCTION memory.reclaim_memory_jobs(
    p_lease interval DEFAULT interval '15 minutes'
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
DECLARE
    reclaimed bigint;
BEGIN
    IF p_lease <= interval '0 seconds' THEN
        RAISE EXCEPTION 'lease 必须大于 0';
    END IF;
    UPDATE memory.memory_jobs
    SET status = 'pending',
        available_at = now(),
        locked_at = NULL,
        locked_by = NULL,
        updated_at = now(),
        last_error_code = 'lease_expired'
    WHERE status = 'running'
      AND locked_at < now() - p_lease;
    GET DIAGNOSTICS reclaimed = ROW_COUNT;
    RETURN reclaimed;
END
$$;

CREATE OR REPLACE FUNCTION memory.retry_memory_job(
    p_job_id uuid,
    p_delay interval DEFAULT interval '5 seconds',
    p_max_attempts smallint DEFAULT 3
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
DECLARE
    retried boolean;
BEGIN
    IF memory.current_app_role() <> 'worker'
       OR memory.current_tenant_id() IS NULL
       OR memory.current_worker_id() IS NULL THEN
        RAISE EXCEPTION '缺少 worker job 上下文';
    END IF;
    IF p_delay < interval '0 seconds' OR p_max_attempts <= 0 THEN
        RAISE EXCEPTION 'retry 参数非法';
    END IF;

    UPDATE memory.memory_jobs job
    SET status = 'pending',
        available_at = now() + p_delay,
        locked_at = NULL,
        locked_by = NULL,
        updated_at = now(),
        last_error_code = 'retry_scheduled'
    WHERE job.tenant_id = memory.current_tenant_id()
      AND job.job_id = p_job_id
      AND job.status = 'running'
      AND job.locked_by = memory.current_worker_id()
      AND job.attempts < p_max_attempts
      AND (
          job.user_id = memory.current_user_id()
          OR (job.user_id IS NULL AND memory.current_user_id() IS NULL)
      );
    retried := FOUND;
    RETURN retried;
END
$$;

CREATE OR REPLACE FUNCTION memory.get_procedural_job_evidence(
    p_job_id uuid
)
RETURNS TABLE (
    run_id uuid,
    request_summary jsonb,
    response_summary jsonb,
    feedback_event text,
    feedback_rating smallint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
BEGIN
    IF memory.current_app_role() <> 'worker'
       OR memory.current_tenant_id() IS NULL
       OR memory.current_worker_id() IS NULL
       OR memory.current_user_id() IS NOT NULL THEN
        RAISE EXCEPTION '缺少 tenant procedural worker 上下文';
    END IF;

    RETURN QUERY
    SELECT run.run_id,
           run.request_summary
               - ARRAY['authorization', 'token', 'tokens', 'image',
                       'images', 'image_keys', 'conversation_state'],
           run.response_summary
               - ARRAY['authorization', 'token', 'tokens', 'image',
                       'images', 'image_keys', 'conversation_state'],
           feedback.event,
           feedback.rating
    FROM memory.memory_jobs job
    CROSS JOIN LATERAL jsonb_array_elements_text(
        coalesce(job.payload -> 'run_ids', '[]'::jsonb)
    ) requested(run_id_text)
    JOIN memory.assistant_runs run
      ON run.tenant_id = job.tenant_id
     AND run.run_id = requested.run_id_text::uuid
    JOIN memory.assistant_feedback feedback
      ON feedback.tenant_id = run.tenant_id
     AND feedback.run_id = run.run_id
    WHERE job.tenant_id = memory.current_tenant_id()
      AND job.job_id = p_job_id
      AND job.job_type = 'procedural_optimize'
      AND job.user_id IS NULL
      AND job.status = 'running'
      AND job.locked_by = memory.current_worker_id();
END
$$;

CREATE OR REPLACE FUNCTION memory._switch_prompt(
    p_tenant_id uuid,
    p_prompt_key text,
    p_version_id uuid,
    p_expected_generation bigint,
    p_actor_user_id uuid,
    p_event_id uuid,
    p_action text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
DECLARE
    current_generation bigint;
    next_generation bigint;
    previous_version uuid;
BEGIN
    IF memory.current_tenant_id() IS DISTINCT FROM p_tenant_id
       OR memory.current_user_id() IS DISTINCT FROM p_actor_user_id
       OR memory.current_app_role() <> 'tenant_admin' THEN
        RAISE EXCEPTION '无权切换程序版本';
    END IF;
    IF p_action NOT IN ('prompt_activated', 'prompt_rolled_back') THEN
        RAISE EXCEPTION '不支持的程序版本动作';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(p_tenant_id::text || ':' || p_prompt_key, 0)
    );

    SELECT active.generation, active.version_id
    INTO current_generation, previous_version
    FROM memory.procedural_prompt_active active
    WHERE active.tenant_id = p_tenant_id
      AND active.prompt_key = p_prompt_key
    FOR UPDATE;

    current_generation := coalesce(current_generation, 0);
    IF current_generation <> p_expected_generation THEN
        RAISE EXCEPTION '程序版本 generation 冲突';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM memory.procedural_prompt_versions version
        WHERE version.tenant_id = p_tenant_id
          AND version.prompt_key = p_prompt_key
          AND version.version_id = p_version_id
          AND version.status = 'approved'
    ) THEN
        RAISE EXCEPTION '目标程序版本不存在或未批准';
    END IF;

    next_generation := current_generation + 1;
    INSERT INTO memory.procedural_prompt_active (
        tenant_id, prompt_key, version_id, generation,
        activated_by, activated_at
    ) VALUES (
        p_tenant_id, p_prompt_key, p_version_id, next_generation,
        p_actor_user_id, now()
    )
    ON CONFLICT (tenant_id, prompt_key) DO UPDATE
    SET version_id = EXCLUDED.version_id,
        generation = EXCLUDED.generation,
        activated_by = EXCLUDED.activated_by,
        activated_at = EXCLUDED.activated_at;

    INSERT INTO memory.audit_events (
        tenant_id, event_id, actor_user_id, actor_type, action,
        resource_type, resource_id, details, expires_at
    ) VALUES (
        p_tenant_id, p_event_id, p_actor_user_id, 'user', p_action,
        'procedural_prompt', p_prompt_key,
        jsonb_build_object(
            'previous_version_id', previous_version,
            'version_id', p_version_id,
            'generation', next_generation
        ),
        now() + interval '365 days'
    );
    RETURN next_generation;
END
$$;

CREATE OR REPLACE FUNCTION memory.activate_prompt(
    p_tenant_id uuid,
    p_prompt_key text,
    p_version_id uuid,
    p_expected_generation bigint,
    p_actor_user_id uuid,
    p_event_id uuid
)
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
    SELECT memory._switch_prompt(
        p_tenant_id, p_prompt_key, p_version_id,
        p_expected_generation, p_actor_user_id, p_event_id,
        'prompt_activated'
    )
$$;

CREATE OR REPLACE FUNCTION memory.rollback_prompt(
    p_tenant_id uuid,
    p_prompt_key text,
    p_version_id uuid,
    p_expected_generation bigint,
    p_actor_user_id uuid,
    p_event_id uuid
)
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
    SELECT memory._switch_prompt(
        p_tenant_id, p_prompt_key, p_version_id,
        p_expected_generation, p_actor_user_id, p_event_id,
        'prompt_rolled_back'
    )
$$;

CREATE OR REPLACE FUNCTION memory.get_active_prompt(
    p_prompt_key text
)
RETURNS TABLE (
    prompt_key text,
    version_id uuid,
    generation bigint,
    content text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
BEGIN
    IF memory.current_tenant_id() IS NULL
       OR memory.current_app_role() NOT IN ('user', 'tenant_admin', 'worker') THEN
        RAISE EXCEPTION '缺少 prompt 读取上下文';
    END IF;
    RETURN QUERY
    SELECT active.prompt_key,
           version.version_id,
           active.generation,
           version.content
    FROM memory.procedural_prompt_active active
    JOIN memory.procedural_prompt_versions version
      ON version.tenant_id = active.tenant_id
     AND version.prompt_key = active.prompt_key
     AND version.version_id = active.version_id
    WHERE active.tenant_id = memory.current_tenant_id()
      AND active.prompt_key = p_prompt_key
      AND version.status = 'approved';
END
$$;

CREATE OR REPLACE FUNCTION memory.mark_expired_memories(
    p_now timestamptz DEFAULT now()
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
DECLARE
    semantic_count bigint;
    episodic_count bigint;
BEGIN
    UPDATE memory.semantic_memories
    SET status = 'deleted', embedding = NULL,
        deleted_at = p_now, updated_at = p_now
    WHERE status = 'active'
      AND expires_at IS NOT NULL
      AND expires_at <= p_now;
    GET DIAGNOSTICS semantic_count = ROW_COUNT;

    UPDATE memory.episodic_memories
    SET status = 'deleted', embedding = NULL,
        deleted_at = p_now, updated_at = p_now
    WHERE status IN ('pending', 'active')
      AND expires_at <= p_now;
    GET DIAGNOSTICS episodic_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'semantic', semantic_count,
        'episodic', episodic_count
    );
END
$$;

CREATE OR REPLACE FUNCTION memory.purge_expired_rows(
    p_now timestamptz DEFAULT now(),
    p_delete_grace interval DEFAULT interval '24 hours'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, memory, public
AS $$
DECLARE
    thread_count bigint;
    semantic_count bigint;
    episodic_count bigint;
    job_count bigint;
    audit_count bigint;
BEGIN
    IF p_delete_grace < interval '0 seconds' THEN
        RAISE EXCEPTION '删除宽限期不能为负数';
    END IF;

    DELETE FROM memory.assistant_threads WHERE expires_at <= p_now;
    GET DIAGNOSTICS thread_count = ROW_COUNT;
    DELETE FROM memory.semantic_memories
    WHERE status = 'deleted' AND deleted_at <= p_now - p_delete_grace;
    GET DIAGNOSTICS semantic_count = ROW_COUNT;
    DELETE FROM memory.episodic_memories
    WHERE status = 'deleted' AND deleted_at <= p_now - p_delete_grace;
    GET DIAGNOSTICS episodic_count = ROW_COUNT;
    DELETE FROM memory.memory_jobs
    WHERE status IN ('done', 'failed') AND expires_at <= p_now;
    GET DIAGNOSTICS job_count = ROW_COUNT;
    DELETE FROM memory.audit_events WHERE expires_at <= p_now;
    GET DIAGNOSTICS audit_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'threads', thread_count,
        'semantic', semantic_count,
        'episodic', episodic_count,
        'jobs', job_count,
        'audit', audit_count
    );
END
$$;

REVOKE ALL ON FUNCTION memory.current_tenant_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.current_user_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.current_app_role() FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.current_worker_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.claim_memory_job(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.reclaim_memory_jobs(interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.retry_memory_job(uuid, interval, smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.get_procedural_job_evidence(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory._switch_prompt(uuid, text, uuid, bigint, uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.activate_prompt(uuid, text, uuid, bigint, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.rollback_prompt(uuid, text, uuid, bigint, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.get_active_prompt(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.mark_expired_memories(timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION memory.purge_expired_rows(timestamptz, interval) FROM PUBLIC;

GRANT USAGE ON SCHEMA memory TO
    shopping_memory_api,
    shopping_memory_worker,
    shopping_memory_poller,
    shopping_memory_maintenance;
GRANT EXECUTE ON FUNCTION memory.current_tenant_id() TO
    shopping_memory_api, shopping_memory_worker;
GRANT EXECUTE ON FUNCTION memory.current_user_id() TO
    shopping_memory_api, shopping_memory_worker;
GRANT EXECUTE ON FUNCTION memory.current_app_role() TO
    shopping_memory_api, shopping_memory_worker;
GRANT EXECUTE ON FUNCTION memory.current_worker_id() TO
    shopping_memory_worker;

GRANT SELECT, INSERT, UPDATE, DELETE ON memory.assistant_threads
    TO shopping_memory_api;
GRANT SELECT, INSERT ON memory.assistant_runs TO shopping_memory_api;
GRANT SELECT, UPDATE (status, embedding, updated_at, deleted_at)
    ON memory.semantic_memories TO shopping_memory_api;
GRANT SELECT, INSERT ON memory.assistant_feedback TO shopping_memory_api;
GRANT SELECT, UPDATE (scope, status, reviewed_by, reviewed_at, updated_at,
                      embedding, deleted_at)
    ON memory.episodic_memories TO shopping_memory_api;
REVOKE SELECT ON memory.procedural_prompt_versions,
    memory.procedural_prompt_active
    FROM shopping_memory_api, shopping_memory_worker;
GRANT INSERT ON memory.procedural_prompt_versions TO shopping_memory_api;
GRANT UPDATE (status, approved_by, approved_at)
    ON memory.procedural_prompt_versions TO shopping_memory_api;
GRANT SELECT, INSERT ON memory.memory_jobs TO shopping_memory_api;
GRANT SELECT, INSERT ON memory.audit_events TO shopping_memory_api;

GRANT SELECT ON memory.assistant_threads, memory.assistant_runs,
    memory.assistant_feedback
    TO shopping_memory_worker;
GRANT SELECT, INSERT, UPDATE ON memory.semantic_memories,
    memory.episodic_memories TO shopping_memory_worker;
GRANT INSERT ON memory.procedural_prompt_versions TO shopping_memory_worker;
REVOKE UPDATE ON memory.memory_jobs FROM shopping_memory_worker;
GRANT SELECT ON memory.memory_jobs TO shopping_memory_worker;
GRANT UPDATE (status, available_at, locked_at, locked_by,
              last_error_code, updated_at)
    ON memory.memory_jobs TO shopping_memory_worker;
GRANT INSERT ON memory.audit_events TO shopping_memory_worker;

GRANT EXECUTE ON FUNCTION memory.claim_memory_job(uuid)
    TO shopping_memory_poller;
GRANT EXECUTE ON FUNCTION memory.reclaim_memory_jobs(interval)
    TO shopping_memory_poller;
GRANT EXECUTE ON FUNCTION memory.retry_memory_job(uuid, interval, smallint)
    TO shopping_memory_worker;
GRANT EXECUTE ON FUNCTION memory.get_procedural_job_evidence(uuid)
    TO shopping_memory_worker;
GRANT EXECUTE ON FUNCTION memory.activate_prompt(uuid, text, uuid, bigint, uuid, uuid)
    TO shopping_memory_api;
GRANT EXECUTE ON FUNCTION memory.rollback_prompt(uuid, text, uuid, bigint, uuid, uuid)
    TO shopping_memory_api;
GRANT EXECUTE ON FUNCTION memory.get_active_prompt(text)
    TO shopping_memory_api, shopping_memory_worker;
GRANT EXECUTE ON FUNCTION memory.mark_expired_memories(timestamptz)
    TO shopping_memory_maintenance;
GRANT EXECUTE ON FUNCTION memory.purge_expired_rows(timestamptz, interval)
    TO shopping_memory_maintenance;

COMMIT;
