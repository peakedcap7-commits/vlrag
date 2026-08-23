import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from src.memory_migrate import (
    LOGIN_ROLE_ENV,
    SCHEMA_PATH,
    require_development_database,
    required_login_passwords,
    set_local_context,
)

ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "assistant_threads",
    "assistant_runs",
    "semantic_memories",
    "assistant_feedback",
    "episodic_memories",
    "procedural_prompt_versions",
    "procedural_prompt_active",
    "memory_jobs",
    "audit_events",
}


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


class MemorySchemaStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.lower_sql = cls.sql.lower()

    def test_forward_schema_has_exact_business_tables(self):
        for table in TABLES:
            with self.subTest(table=table):
                self.assertIn(
                    f"create table if not exists memory.{table}", self.lower_sql
                )
                self.assertIn(
                    f"alter table memory.{table} force row level security",
                    self.lower_sql,
                )

    def test_security_and_lifecycle_functions_exist(self):
        for function in (
            "claim_memory_job",
            "reclaim_memory_jobs",
            "retry_memory_job",
            "get_procedural_job_evidence",
            "activate_prompt",
            "rollback_prompt",
            "get_active_prompt",
            "mark_expired_memories",
            "purge_expired_rows",
        ):
            with self.subTest(function=function):
                self.assertIn(f"function memory.{function}", self.lower_sql)
        self.assertIn("security definer", self.lower_sql)
        self.assertIn("for update skip locked", self.lower_sql)
        self.assertIn("create extension if not exists vector", self.lower_sql)

    def test_schema_avoids_unapproved_components(self):
        for forbidden in (
            "using hnsw",
            "using ivfflat",
            "create table tenants",
            "create table users",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.lower_sql)

    def test_development_database_guard(self):
        self.assertEqual(
            require_development_database("postgresql://db/shopping_qna_test"),
            "shopping_qna_test",
        )
        with self.assertRaises(ValueError):
            require_development_database("postgresql://db/shopping_qna")

    def test_set_local_context_is_parameterized_and_validated(self):
        cursor = FakeCursor()
        tenant_id, user_id = str(uuid4()), str(uuid4())
        set_local_context(cursor, tenant_id, user_id, "user")
        sql, params = cursor.calls[0]
        self.assertIn("set_config('app.tenant_id', %s, true)", sql)
        self.assertEqual(params, (tenant_id, user_id, "user", ""))
        with self.assertRaises(ValueError):
            set_local_context(cursor, tenant_id, user_id, "owner")

    def test_login_passwords_are_environment_only(self):
        environment = {
            env_name: f"safe-development-{index}-password"
            for index, (_, env_name) in enumerate(LOGIN_ROLE_ENV.values())
        }
        with patch.dict(os.environ, environment, clear=True):
            passwords = required_login_passwords()
        self.assertEqual(set(passwords), set(LOGIN_ROLE_ENV))
        self.assertFalse(any(password in self.sql for password in passwords.values()))

    def test_backend_function_signatures_are_stable(self):
        self.assertIn("memory.claim_memory_job(\n    p_worker_id uuid", self.sql)
        self.assertIn("memory.retry_memory_job(\n    p_job_id uuid", self.sql)
        self.assertIn(
            "memory.get_procedural_job_evidence(\n    p_job_id uuid", self.sql
        )
        self.assertIn("memory.activate_prompt(\n    p_tenant_id uuid", self.sql)
        self.assertIn("memory.get_active_prompt(\n    p_prompt_key text", self.sql)
        self.assertIn("p_expected_generation bigint", self.sql)

    def test_retry_only_releases_the_current_workers_job(self):
        body = self.sql.split("FUNCTION memory.retry_memory_job", 1)[1].split("$$;", 1)[
            0
        ]
        self.assertIn("job.status = 'running'", body)
        self.assertIn("job.locked_by = memory.current_worker_id()", body)
        self.assertIn("job.attempts < p_max_attempts", body)
        self.assertIn("status = 'pending'", body)
        self.assertIn("locked_by = NULL", body)

    def test_procedural_evidence_is_claim_scoped_and_redacted(self):
        body = self.sql.split("FUNCTION memory.get_procedural_job_evidence", 1)[
            1
        ].split("$$;", 1)[0]
        self.assertIn("job.job_type = 'procedural_optimize'", body)
        self.assertIn("job.locked_by = memory.current_worker_id()", body)
        self.assertIn("job.payload -> 'run_ids'", body)
        self.assertIn("feedback.event", body)
        self.assertIn("feedback.rating", body)
        self.assertNotIn("feedback.comment", body)
        self.assertNotIn("thread.user_id", body)
        self.assertIn(
            "REVOKE UPDATE ON memory.memory_jobs FROM shopping_memory_worker",
            self.sql,
        )

    def test_active_prompt_uses_approved_pointer_without_table_select(self):
        body = self.sql.split("FUNCTION memory.get_active_prompt", 1)[1].split(
            "$$;", 1
        )[0]
        self.assertIn("version.status = 'approved'", body)
        self.assertIn("active.tenant_id = memory.current_tenant_id()", body)
        self.assertIn("REVOKE SELECT ON memory.procedural_prompt_versions", self.sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION memory.get_active_prompt(text)", self.sql
        )

    def test_episode_worker_and_admin_scopes_are_narrow(self):
        worker_policy = self.sql.split("CREATE POLICY episodic_worker_all", 1)[1].split(
            "DROP POLICY", 1
        )[0]
        self.assertIn("scope = 'user'", worker_policy)
        self.assertIn("scope = 'tenant'", worker_policy)
        self.assertIn("status = 'pending'", worker_policy)
        admin_policy = self.sql.split("CREATE POLICY episodic_api_update", 1)[1].split(
            "DROP POLICY", 1
        )[0]
        self.assertIn("status = 'pending'", admin_policy)
        self.assertIn("status IN ('active', 'rejected')", admin_policy)


@unittest.skipUnless(
    os.getenv("MEMORY_TEST_DATABASE_URL"),
    "未配置 MEMORY_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试",
)
class MemorySchemaIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import psycopg
        except ImportError as exc:
            raise AssertionError("配置了集成数据库但未安装 psycopg 3") from exc

        from src.memory_migrate import migrate

        cls.psycopg = psycopg
        cls.dsn = os.environ["MEMORY_TEST_DATABASE_URL"]
        require_development_database(cls.dsn)
        migrate(cls.dsn)
        migrate(cls.dsn)

    def test_rls_isolates_same_thread_id_between_tenants(self):
        tenant_a, tenant_b = str(uuid4()), str(uuid4())
        user_a, user_b, thread_id = str(uuid4()), str(uuid4()), str(uuid4())
        with (
            self.psycopg.connect(self.dsn) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SET LOCAL ROLE shopping_memory_api")
            set_local_context(cursor, tenant_a, user_a, "user")
            cursor.execute(
                """
                INSERT INTO memory.assistant_threads
                    (tenant_id, thread_id, user_id, expires_at)
                VALUES (%s, %s, %s, now() + interval '1 day')
                """,
                (tenant_a, thread_id, user_a),
            )

        with (
            self.psycopg.connect(self.dsn) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SET LOCAL ROLE shopping_memory_api")
            set_local_context(cursor, tenant_b, user_b, "user")
            cursor.execute(
                "SELECT count(*) FROM memory.assistant_threads WHERE thread_id = %s",
                (thread_id,),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        with (
            self.psycopg.connect(self.dsn) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SET LOCAL ROLE shopping_memory_api")
            set_local_context(cursor, tenant_a, user_a, "user")
            cursor.execute(
                "DELETE FROM memory.assistant_threads WHERE thread_id = %s",
                (thread_id,),
            )


if __name__ == "__main__":
    unittest.main()
