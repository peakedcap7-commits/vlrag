from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import jwt
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
    worker._finish(identity, {"job_id": job_id}, "ValueError")
    sql, params = cursor.calls[0]
    assert "memory.retry_memory_job" in sql
    assert params == (job_id,)


def test_worker_marks_job_failed_when_retry_budget_is_exhausted():
    from src.memory_worker import MemoryWorker

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return {"retried": False}

    cursor = Cursor()

    class Memory:
        @contextmanager
        def transaction(self, *_args):
            yield cursor

    worker = object.__new__(MemoryWorker)
    worker.memory = Memory()
    worker.worker_id = uuid4()
    identity = type("I", (), {"tenant_id": TENANT_A})()
    worker._finish(identity, {"job_id": uuid4()}, "TimeoutError")
    assert len(cursor.calls) == 2
    assert "status=%s" in cursor.calls[1][0]
    assert cursor.calls[1][1][0:2] == ("failed", "TimeoutError")


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
    assert "FROM memory.procedural_prompt_active" not in worker


def test_episode_worker_creates_private_and_pending_shared_candidates():
    from src.memory_worker import _redact

    source = (Path(__file__).parents[1] / "src/memory_worker.py").read_text(encoding="utf-8")
    assert "'user',%s,%s,%s,%s,%s,%s::vector,'active'" in source
    assert "NULL,'tenant',%s,%s,%s,%s,%s,%s::vector,'pending'" in source
    assert "Identity(identity.tenant_id, None" in source
    assert "f.feedback_id=%s" in source
    assert "f.rating>=4" in source
    assert "13800138000" not in _redact("电话 13800138000，邮箱 a@example.com")
    assert "a@example.com" not in _redact("电话 13800138000，邮箱 a@example.com")


def test_compose_declares_required_services_and_no_redis_or_celery():
    compose = (Path(__file__).parents[1] / "compose.yaml").read_text(encoding="utf-8")
    for service in ("api:", "worker:", "postgres:", "neo4j:", "minio:", "bootstrap:"):
        assert service in compose
    assert "redis:" not in compose
    assert "celery" not in compose.lower()
