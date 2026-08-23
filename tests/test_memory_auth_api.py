from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.auth import LocalJWTAuthenticator
from src.memory import MemoryService, NullMemoryService

SECRET = "0123456789abcdef0123456789abcdef"
TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER = UUID("22222222-2222-2222-2222-222222222222")


class FakeService:
    def recommend(self, query, *_args):
        return {"query": query, "anchor": None, "outfit_candidates": []}

    def close(self):
        pass


class FakeGraph:
    def invoke(self, _payload):
        return {
            "intent": "single_item_recommend",
            "status": "ok",
            "result": None,
            "response_message": "ok",
        }


class FakeMemory:
    enabled = True

    def __init__(self):
        self.identities = []

    def load_thread(self, identity, _thread_id):
        self.identities.append(identity)
        return {"candidate_item_ids": ["stored"]}

    def load_context(self, identity, *_args):
        self.identities.append(identity)
        return {"semantic": [], "episodic": [], "procedural": {}}

    def record_run(self, identity, *_args):
        self.identities.append(identity)
        return uuid4()

    def close(self):
        pass


def client_and_auth():
    auth = LocalJWTAuthenticator(SECRET)
    memory = FakeMemory()
    app = create_app(
        FakeService(),
        assistant_graph=FakeGraph(),
        authenticator=auth,
        memory_service=memory,
    )
    return TestClient(app), auth, memory


def test_jwt_fixed_algorithm_and_required_claims():
    auth = LocalJWTAuthenticator(SECRET)
    token = auth.issue(TENANT_A, USER, ["user"])
    identity = auth.decode(token)
    assert identity.tenant_id == TENANT_A
    assert identity.user_id == USER

    now = datetime.now(timezone.utc)
    invalid = jwt.encode(
        {
            "iss": "shopping-qna-dev",
            "aud": "shopping-qna-api",
            "sub": str(USER),
            "tenant_id": str(TENANT_A),
            "roles": ["owner"],
            "iat": now,
            "exp": now + timedelta(minutes=1),
            "jti": str(uuid4()),
        },
        SECRET,
        algorithm="HS256",
    )
    try:
        auth.decode(invalid)
    except Exception as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("未知角色必须被拒绝")


def test_business_routes_require_auth_and_body_cannot_supply_identity():
    client, auth, _memory = client_and_auth()
    payload = {
        "thread_id": str(uuid4()),
        "message": "蓝色裤子",
        "top_k": 5,
        "retrieval_limit": 3,
    }
    assert client.get("/health").status_code == 200
    assert client.post("/assistant/message", json=payload).status_code == 401

    payload["tenant_id"] = str(TENANT_B)
    response = client.post(
        "/assistant/message",
        json=payload,
        headers={"Authorization": f"Bearer {auth.issue(TENANT_A, USER)}"},
    )
    assert response.status_code == 422


def test_same_user_tokens_keep_tenant_context_separate():
    client, auth, memory = client_and_auth()
    for tenant in (TENANT_A, TENANT_B):
        response = client.post(
            "/assistant/message",
            json={
                "thread_id": str(uuid4()),
                "message": "继续",
                "top_k": 5,
                "retrieval_limit": 3,
            },
            headers={"Authorization": f"Bearer {auth.issue(tenant, USER)}"},
        )
        assert response.status_code == 200
    assert {identity.tenant_id for identity in memory.identities} == {TENANT_A, TENANT_B}


def test_admin_route_rejects_normal_user():
    client, auth, _memory = client_and_auth()
    response = client.post(
        "/warmup",
        headers={"Authorization": f"Bearer {auth.issue(TENANT_A, USER, ['user'])}"},
    )
    assert response.status_code == 403


def test_admin_uuid_path_is_validated_before_service_call():
    client, auth, _memory = client_and_auth()
    response = client.post(
        "/admin/prompts/outfit_revise/versions/not-a-uuid/approve",
        headers={
            "Authorization": f"Bearer {auth.issue(TENANT_A, USER, ['tenant_admin'])}"
        },
    )
    assert response.status_code == 422


def test_memory_feature_off_keeps_request_path_available():
    service = NullMemoryService()
    assert service.load_thread(None, uuid4()) is None
    assert service.load_context(None, "test") == {
        "semantic": [],
        "episodic": [],
        "procedural": {},
    }
    assert service.record_run(None, uuid4(), {}, {})


def test_write_flag_keeps_thread_and_run_but_skips_memory_job():
    class Cursor:
        rowcount = 1

        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

    cursor = Cursor()
    memory = object.__new__(MemoryService)
    memory.write_enabled = False
    memory.semantic_enabled = True

    @contextmanager
    def transaction(*_args):
        yield cursor

    memory.transaction = transaction
    identity = type("I", (), {"tenant_id": TENANT_A, "user_id": USER})()
    memory.record_run(
        identity,
        uuid4(),
        {"message": "test"},
        {"intent": "outfit_revise", "status": "ok", "response_message": "ok"},
    )
    sql = " ".join(call[0] for call in cursor.calls)
    assert "assistant_threads" in sql
    assert "assistant_runs" in sql
    assert "memory_jobs" not in sql


def test_prompt_optimization_respects_write_and_procedural_flags():
    memory = object.__new__(MemoryService)
    memory.write_enabled = False
    memory.procedural_enabled = True
    identity = type(
        "I",
        (),
        {"is_admin": True, "tenant_id": TENANT_A, "user_id": USER},
    )()
    with pytest.raises(HTTPException) as caught:
        memory.optimize_prompt(identity, "outfit_revise", [uuid4()])
    assert caught.value.status_code == 503


def test_procedural_recall_only_uses_active_pointer():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    cursor = Cursor()
    memory = object.__new__(MemoryService)
    memory.read_enabled = True
    memory.semantic_enabled = False
    memory.episodic_enabled = False
    memory.procedural_enabled = True
    memory.embeddings = None

    @contextmanager
    def transaction(*_args):
        yield cursor

    memory.transaction = transaction
    identity = type("I", (), {"tenant_id": TENANT_A, "user_id": USER})()
    context = memory.load_context(identity, "", ("outfit_revise",))
    assert context["procedural"] == {}
    sql = cursor.calls[0][0]
    assert "memory.get_active_prompt" in sql
    assert "procedural_prompt_versions" not in sql


def test_worker_retry_is_idempotent_and_lease_bound():
    from src.memory_worker import MemoryWorker

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return {"retried": True}

    cursor = Cursor()

    class Memory:
        @contextmanager
        def transaction(self, *_args):
            yield cursor

    worker = object.__new__(MemoryWorker)
    worker.memory = Memory()
    worker.worker_id = uuid4()
    identity = type("I", (), {"tenant_id": TENANT_A})()
    job_id = uuid4()
    worker._finish(identity, {"job_id": job_id}, "valueerror")
    sql, params = cursor.calls[0]
    assert "memory.retry_memory_job" in sql
    assert "3::integer" in sql
    assert params == (job_id,)


def test_worker_marks_job_failed_when_retry_budget_is_exhausted():
    from src.memory_worker import MemoryWorker

    class Cursor:
        def __init__(self):
            self.calls = []
            self.results = iter(({"retried": False}, {"completed": True}))

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return next(self.results)

    cursor = Cursor()

    class Memory:
        @contextmanager
        def transaction(self, *_args):
            yield cursor

    worker = object.__new__(MemoryWorker)
    worker.memory = Memory()
    worker.worker_id = uuid4()
    identity = type("I", (), {"tenant_id": TENANT_A})()
    job_id = uuid4()
    worker._finish(identity, {"job_id": job_id}, "timeouterror")
    assert len(cursor.calls) == 2
    assert "memory.complete_memory_job" in cursor.calls[1][0]
    assert cursor.calls[1][1] == (job_id, "failed", "timeouterror")


def test_worker_rejects_false_job_completion():
    from src.memory_worker import MemoryWorker

    class Cursor:
        def execute(self, _sql, _params):
            pass

        def fetchone(self):
            return {"completed": False}

    class Memory:
        @contextmanager
        def transaction(self, *_args):
            yield Cursor()

    worker = object.__new__(MemoryWorker)
    worker.memory = Memory()
    worker.worker_id = uuid4()
    identity = type("I", (), {"tenant_id": TENANT_A})()
    with pytest.raises(RuntimeError, match="memory_job_completion_rejected"):
        worker._finish(identity, {"job_id": uuid4()}, None)


def test_worker_logs_only_safe_job_failure_fields(caplog):
    import json
    import logging

    from src.memory_worker import MemoryWorker

    job_id = uuid4()
    job = {
        "tenant_id": TENANT_A,
        "job_id": job_id,
        "user_id": USER,
        "job_type": "semantic_extract",
        "payload": {"secret": "do-not-log"},
    }
    worker = object.__new__(MemoryWorker)
    worker.claim = lambda: job

    def fail(*_args):
        raise ValueError("secret")

    worker._semantic = fail
    worker._finish = lambda *_args: None
    with caplog.at_level(logging.ERROR, logger="shopping_qna.memory_worker"):
        assert worker.run_once()
    record = json.loads(caplog.records[-1].message)
    assert record == {
        "event": "memory_job_failed",
        "job_id": str(job_id),
        "job_type": "semantic_extract",
        "error_code": "valueerror",
    }
    assert "do-not-log" not in caplog.text


def test_episode_approval_writes_body_free_audit_event():
    class Cursor:
        rowcount = 1

        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

    cursor = Cursor()
    memory = object.__new__(MemoryService)

    @contextmanager
    def transaction(*_args):
        yield cursor

    memory.transaction = transaction
    identity = type(
        "I",
        (),
        {"is_admin": True, "tenant_id": TENANT_A, "user_id": USER},
    )()
    memory_id = uuid4()
    memory.approve_episode(identity, memory_id)
    audit_sql, audit_params = cursor.calls[1]
    assert "audit_events" in audit_sql
    assert not {"observation", "action", "result"} & set(audit_sql.lower().split())
    assert audit_params[-1] == str(memory_id)


def test_prompt_switch_conflict_maps_to_generic_409():
    class Conflict(Exception):
        sqlstate = "P0001"

    class Cursor:
        def execute(self, _sql, _params):
            raise Conflict("database detail must stay private")

    memory = object.__new__(MemoryService)

    @contextmanager
    def transaction(*_args):
        yield Cursor()

    memory.transaction = transaction
    identity = type(
        "I",
        (),
        {"is_admin": True, "tenant_id": TENANT_A, "user_id": USER},
    )()
    with pytest.raises(HTTPException) as caught:
        memory.activate_prompt(identity, "outfit_revise", uuid4(), 0)
    assert caught.value.status_code == 409
    assert caught.value.detail == "程序版本状态冲突"
    assert "database detail" not in caught.value.detail


def test_prompt_management_uses_controlled_database_functions():
    source = (Path(__file__).parents[1] / "src/memory.py").read_text(encoding="utf-8")
    worker = (Path(__file__).parents[1] / "src/memory_worker.py").read_text(
        encoding="utf-8"
    )
    assert "memory.list_prompt_versions" in source
    assert "memory.get_active_prompt" in source
    assert "memory.approve_prompt" in source
    assert "UPDATE memory.procedural_prompt_versions" not in source
    assert "memory.get_procedural_job_evidence" in worker
    assert "memory.complete_memory_job" in worker
    assert "UPDATE memory.memory_jobs" not in worker
    assert "FROM memory.procedural_prompt_active" not in worker
    assert "ON CONFLICT (tenant_id,user_id,dimension,lower(value),polarity)" in worker
    assert "DO UPDATE SET context=EXCLUDED.context" in worker
    assert "ON CONFLICT (tenant_id,prompt_key,content_hash) DO NOTHING" in worker
    for flag in (
        "read_enabled=MEMORY_READ_ENABLED",
        "write_enabled=MEMORY_WRITE_ENABLED",
        "semantic_enabled=SEMANTIC_MEMORY_ENABLED",
        "episodic_enabled=EPISODIC_MEMORY_ENABLED",
        "procedural_enabled=PROCEDURAL_MEMORY_ENABLED",
    ):
        assert flag in worker


def test_episode_worker_creates_private_and_pending_shared_candidates():
    from src.auth import Identity
    from src.memory_worker import EpisodeMemory, MemoryWorker, _redact

    evidence = {
        "request_summary": {"message": "test"},
        "response_summary": {"message": "ok"},
        "feedback_id": uuid4(),
        "event": "accepted",
        "rating": None,
        "comment": None,
    }

    class Cursor:
        def __init__(self, memory, row=None):
            self.memory = memory
            self.row = row

        def execute(self, sql, params):
            self.memory.calls.append((sql, params))

        def fetchone(self):
            return self.row

    class Memory:
        def __init__(self):
            self.calls = []
            self.identities = []
            self.embeddings = type(
                "E",
                (),
                {"embed_documents": lambda _self, texts: [[0.0] * 1024 for _ in texts]},
            )()

        @contextmanager
        def transaction(self, identity, *_args):
            self.identities.append(identity)
            yield Cursor(self, evidence if len(self.identities) == 1 else None)

    memory = Memory()
    worker = object.__new__(MemoryWorker)
    worker.memory = memory
    worker.worker_id = uuid4()
    worker.episode_manager = type(
        "M",
        (),
        {
            "invoke": lambda _self, _payload: [
                EpisodeMemory(observation="o1", action="a1", result="r1"),
                EpisodeMemory(observation="o2", action="a2", result="r2"),
            ]
        },
    )()
    identity = Identity(TENANT_A, USER, frozenset())
    job = {
        "job_id": uuid4(),
        "source_run_id": uuid4(),
        "payload": {"feedback_id": str(evidence["feedback_id"])},
    }
    worker._episodic(identity, job)

    inserts = memory.calls[1:]
    assert len(inserts) == 4
    assert [params[-2] for _sql, params in inserts] == [0, 1, 0, 1]
    assert all(params[-3] == job["job_id"] for _sql, params in inserts)
    assert all("source_job_id,source_item_index" in sql for sql, _params in inserts)
    assert all("ON CONFLICT (tenant_id,source_job_id,scope,source_item_index)" in sql for sql, _params in inserts)
    assert all("WHERE source_job_id IS NOT NULL DO NOTHING" in sql for sql, _params in inserts)
    assert "'active'" in inserts[0][0]
    assert "'pending'" in inserts[-1][0]
    assert memory.identities[-1].user_id is None
    assert "13800138000" not in _redact("电话 13800138000，邮箱 a@example.com")
    assert "a@example.com" not in _redact("电话 13800138000，邮箱 a@example.com")


def test_compose_declares_required_services_and_no_redis_or_celery():
    compose = (Path(__file__).parents[1] / "compose.yaml").read_text(encoding="utf-8")
    for service in ("api:", "worker:", "postgres:", "neo4j:", "minio:", "bootstrap:"):
        assert service in compose
    assert "redis:" not in compose
    assert "celery" not in compose.lower()


def test_compose_builds_one_shared_application_image():
    compose = (Path(__file__).parents[1] / "compose.yaml").read_text(encoding="utf-8")
    assert compose.count("image: shopping-qna-dev-app") == 4
    assert compose.count("build: .") == 1


def test_docker_installs_cpu_only_torch():
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "torch==2.6.0+cpu" in dockerfile
    assert "https://download.pytorch.org/whl/cpu" in dockerfile
