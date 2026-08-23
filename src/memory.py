"""多租户记忆的最小 PostgreSQL 应用服务。"""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

POSITIVE_FEEDBACK = frozenset({"accepted", "saved", "purchased", "thumbs_up"})
PROMPT_KEYS = frozenset({"outfit_analyze", "outfit_revise"})


def _now():
    return datetime.now(timezone.utc)


def _vector(value):
    if len(value) != 1024:
        raise ValueError("记忆向量必须为 1024 维")
    return "[" + ",".join(str(float(item)) for item in value) + "]"


def _response_summary(state):
    """只保留情景抽取需要的用户态结果，不保存商品或存储标识。"""
    summary = {"message": state.get("response_message", "")[:2000]}
    result = state.get("result")
    if not isinstance(result, dict):
        return summary
    allowed = {
        "verdict",
        "summary",
        "strengths",
        "issues",
        "suggestions",
        "changes",
        "exclude_categories",
        "prefer_categories",
        "prefer_colors",
        "style_shift",
        "rewrite_scope",
    }
    summary["result"] = {key: value for key, value in result.items() if key in allowed}
    return summary


class NullMemoryService:
    """未配置数据库时保留原有业务行为。"""

    enabled = False

    def load_thread(self, *_args):
        return None

    def load_context(self, *_args):
        return {"semantic": [], "episodic": [], "procedural": {}}

    def record_run(self, *_args, **_kwargs):
        return uuid4()

    def close(self):
        pass

    def health(self):
        return False


class MemoryService:
    """直接复用九张已批准表；不增加 repository/factory。"""

    enabled = True

    def __init__(
        self,
        database_url,
        *,
        embeddings=None,
        read_enabled=True,
        write_enabled=True,
        semantic_enabled=True,
        episodic_enabled=True,
        procedural_enabled=True,
    ):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        self.embeddings = embeddings
        self.read_enabled = read_enabled
        self.write_enabled = write_enabled
        self.semantic_enabled = semantic_enabled
        self.episodic_enabled = episodic_enabled
        self.procedural_enabled = procedural_enabled

    @contextmanager
    def transaction(self, identity, role=None, worker_id=None):
        with self.pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.tenant_id', %s, true), "
                    "set_config('app.user_id', %s, true), "
                    "set_config('app.role', %s, true), "
                    "set_config('app.worker_id', %s, true)",
                    (
                        str(identity.tenant_id),
                        str(identity.user_id) if identity.user_id else "",
                        role or ("tenant_admin" if identity.is_admin else "user"),
                        str(worker_id or ""),
                    ),
                )
                yield cursor

    def load_thread(self, identity, thread_id):
        if not self.read_enabled:
            return None
        with self.transaction(identity) as cursor:
            cursor.execute(
                "SELECT conversation_state FROM memory.assistant_threads "
                "WHERE tenant_id=%s AND thread_id=%s AND user_id=%s "
                "AND expires_at > now()",
                (identity.tenant_id, thread_id, identity.user_id),
            )
            row = cursor.fetchone()
            return row["conversation_state"] if row else None

    def load_context(self, identity, message, prompt_keys=()):
        context = {"semantic": [], "episodic": [], "procedural": {}}
        if not self.read_enabled:
            return context
        query_vector = None
        if message.strip() and self.embeddings and (self.semantic_enabled or self.episodic_enabled):
            query_vector = _vector(self.embeddings.embed_query(message))
        with self.transaction(identity) as cursor:
            if query_vector and self.semantic_enabled:
                cursor.execute(
                    "SELECT memory_id, dimension, value, polarity, context, confidence "
                    "FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s "
                    "AND status='active' AND (expires_at IS NULL OR expires_at>now()) "
                    "ORDER BY embedding <=> %s::vector LIMIT 5",
                    (identity.tenant_id, identity.user_id, query_vector),
                )
                context["semantic"] = list(cursor.fetchall())
            if query_vector and self.episodic_enabled:
                cursor.execute(
                    "SELECT memory_id, scope, observation, action, result "
                    "FROM memory.episodic_memories WHERE tenant_id=%s AND status='active' "
                    "AND expires_at>now() AND ((scope='user' AND owner_user_id=%s) "
                    "OR scope='tenant') ORDER BY embedding <=> %s::vector LIMIT 3",
                    (identity.tenant_id, identity.user_id, query_vector),
                )
                context["episodic"] = list(cursor.fetchall())
            if self.procedural_enabled and prompt_keys:
                for prompt_key in prompt_keys:
                    cursor.execute(
                        "SELECT * FROM memory.get_active_prompt(%s)",
                        (prompt_key,),
                    )
                    row = cursor.fetchone()
                    if row:
                        context["procedural"][row["prompt_key"]] = row
        return context

    def record_run(self, identity, thread_id, payload, state, run_id=None):
        run_id = run_id or uuid4()
        now = _now()
        expires_at = now + timedelta(days=30)
        conversation_state = payload.get("conversation_state") or {}
        with self.transaction(identity) as cursor:
            cursor.execute(
                "INSERT INTO memory.assistant_threads "
                "(tenant_id,thread_id,user_id,conversation_state,last_intent,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id,thread_id) DO UPDATE SET "
                "conversation_state=EXCLUDED.conversation_state,last_intent=EXCLUDED.last_intent,"
                "updated_at=now(),expires_at=EXCLUDED.expires_at "
                "WHERE memory.assistant_threads.user_id=EXCLUDED.user_id",
                (
                    identity.tenant_id,
                    thread_id,
                    identity.user_id,
                    json.dumps(conversation_state),
                    getattr(state["intent"], "value", state["intent"]),
                    expires_at,
                ),
            )
            if cursor.rowcount != 1:
                raise HTTPException(404, "thread 不存在")
            prompt = state.get("active_prompt") or {}
            cursor.execute(
                "INSERT INTO memory.assistant_runs "
                "(tenant_id,run_id,thread_id,intent,status,request_summary,response_summary,"
                "prompt_key,prompt_version_id,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    identity.tenant_id,
                    run_id,
                    thread_id,
                    getattr(state["intent"], "value", state["intent"]),
                    state["status"],
                    json.dumps({"message": payload.get("message", "")[:2000]}),
                    json.dumps(_response_summary(state), ensure_ascii=False),
                    prompt.get("prompt_key"),
                    prompt.get("version_id"),
                    expires_at,
                ),
            )
            if state["status"] == "ok" and self.write_enabled and self.semantic_enabled:
                self._enqueue(
                    cursor,
                    identity.tenant_id,
                    identity.user_id,
                    "semantic_extract",
                    str(run_id),
                    run_id,
                    {"message": payload.get("message", "")[:2000]},
                )
        return run_id

    @staticmethod
    def _enqueue(cursor, tenant_id, user_id, job_type, dedupe_key, source_run_id, payload, job_id=None):
        job_id = job_id or uuid4()
        cursor.execute(
            "INSERT INTO memory.memory_jobs "
            "(tenant_id,job_id,user_id,job_type,source_run_id,dedupe_key,payload,status,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',now()+interval '30 days') "
            "ON CONFLICT (tenant_id,job_type,dedupe_key) DO NOTHING",
            (tenant_id, job_id, user_id, job_type, source_run_id, dedupe_key, json.dumps(payload)),
        )
        return job_id

    def add_feedback(self, identity, payload):
        feedback_id = uuid4()
        with self.transaction(identity) as cursor:
            cursor.execute(
                "INSERT INTO memory.assistant_feedback "
                "(tenant_id,feedback_id,run_id,event,rating,comment,idempotency_key,expires_at) "
                "SELECT %s,%s,r.run_id,%s,%s,%s,%s,least(r.expires_at,now()+interval '180 days') "
                "FROM memory.assistant_runs r JOIN memory.assistant_threads t USING (tenant_id,thread_id) "
                "WHERE r.tenant_id=%s AND r.run_id=%s AND r.thread_id=%s AND t.user_id=%s "
                "ON CONFLICT (tenant_id,run_id,idempotency_key) DO NOTHING RETURNING feedback_id",
                (
                    identity.tenant_id,
                    feedback_id,
                    payload.event,
                    payload.rating,
                    payload.comment,
                    payload.idempotency_key,
                    identity.tenant_id,
                    payload.run_id,
                    payload.thread_id,
                    identity.user_id,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT feedback_id FROM memory.assistant_feedback WHERE tenant_id=%s "
                    "AND run_id=%s AND idempotency_key=%s",
                    (identity.tenant_id, payload.run_id, payload.idempotency_key),
                )
                row = cursor.fetchone()
            if row is None:
                raise HTTPException(404, "run 不存在")
            feedback_id = row["feedback_id"]
            positive = payload.event in POSITIVE_FEEDBACK or (
                payload.event == "rating" and payload.rating and payload.rating >= 4
            )
            if positive and self.write_enabled and self.episodic_enabled:
                self._enqueue(
                    cursor,
                    identity.tenant_id,
                    identity.user_id,
                    "episodic_extract",
                    str(feedback_id),
                    payload.run_id,
                    {"feedback_id": str(feedback_id)},
                )
        return feedback_id

    def list_memories(self, identity, memory_type):
        with self.transaction(identity) as cursor:
            if memory_type == "semantic":
                cursor.execute(
                    "SELECT memory_id,dimension,value,polarity,context,confidence,created_at "
                    "FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s AND status='active' "
                    "ORDER BY updated_at DESC",
                    (identity.tenant_id, identity.user_id),
                )
            else:
                cursor.execute(
                    "SELECT memory_id,scope,observation,action,result,created_at "
                    "FROM memory.episodic_memories WHERE tenant_id=%s AND owner_user_id=%s "
                    "AND scope='user' AND status='active' ORDER BY updated_at DESC",
                    (identity.tenant_id, identity.user_id),
                )
            return list(cursor.fetchall())

    def delete_memory(self, identity, memory_id):
        with self.transaction(identity) as cursor:
            cursor.execute(
                "UPDATE memory.semantic_memories SET status='deleted',embedding=NULL,deleted_at=now(),updated_at=now() "
                "WHERE tenant_id=%s AND memory_id=%s AND user_id=%s AND status<>'deleted' RETURNING 'semantic' kind",
                (identity.tenant_id, memory_id, identity.user_id),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "UPDATE memory.episodic_memories SET status='deleted',embedding=NULL,deleted_at=now(),updated_at=now() "
                    "WHERE tenant_id=%s AND memory_id=%s AND owner_user_id=%s AND scope='user' "
                    "AND status<>'deleted' RETURNING 'episodic' kind",
                    (identity.tenant_id, memory_id, identity.user_id),
                )
                row = cursor.fetchone()
            if row is None:
                raise HTTPException(404, "记忆不存在")
            cursor.execute(
                "INSERT INTO memory.audit_events "
                "(tenant_id,event_id,actor_user_id,actor_type,action,resource_type,resource_id,details,expires_at) "
                "VALUES (%s,%s,%s,'user','memory.delete',%s,%s,'{}',now()+interval '365 days')",
                (identity.tenant_id, uuid4(), identity.user_id, row["kind"], str(memory_id)),
            )

    def optimize_prompt(self, identity, prompt_key, run_ids):
        self._require_admin(identity)
        self._require_prompt_key(prompt_key)
        if not self.write_enabled or not self.procedural_enabled:
            raise HTTPException(503, "程序记忆写入已禁用")
        job_id = uuid4()
        with self.transaction(identity) as cursor:
            self._enqueue(
                cursor,
                identity.tenant_id,
                None,
                "procedural_optimize",
                f"{prompt_key}:{job_id}",
                None,
                {
                    "prompt_key": prompt_key,
                    "created_by": str(identity.user_id),
                    "run_ids": [str(run_id) for run_id in run_ids],
                },
                job_id,
            )
        return job_id

    def list_prompt_versions(self, identity, prompt_key):
        self._require_admin(identity)
        self._require_prompt_key(prompt_key)
        with self.transaction(identity) as cursor:
            cursor.execute(
                "SELECT * FROM memory.list_prompt_versions(%s)",
                (prompt_key,),
            )
            return list(cursor.fetchall())

    def approve_prompt(self, identity, prompt_key, version_id):
        self._require_admin(identity)
        self._require_prompt_key(prompt_key)
        with self.transaction(identity) as cursor:
            cursor.execute(
                "SELECT memory.approve_prompt(%s,%s,%s,%s) AS approved",
                (prompt_key, version_id, identity.user_id, uuid4()),
            )
            if not cursor.fetchone()["approved"]:
                raise HTTPException(409, "版本不可审批")

    def activate_prompt(self, identity, prompt_key, version_id, expected_generation, rollback=False):
        self._require_admin(identity)
        self._require_prompt_key(prompt_key)
        try:
            with self.transaction(identity) as cursor:
                function = "memory.rollback_prompt" if rollback else "memory.activate_prompt"
                cursor.execute(
                    f"SELECT {function}(%s,%s,%s,%s,%s,%s) AS generation",
                    (identity.tenant_id, prompt_key, version_id, expected_generation, identity.user_id, uuid4()),
                )
                return cursor.fetchone()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"P0001", "40001", "40P01"}:
                raise HTTPException(409, "程序版本状态冲突") from None
            raise

    def approve_episode(self, identity, memory_id):
        self._require_admin(identity)
        with self.transaction(identity) as cursor:
            cursor.execute(
                "UPDATE memory.episodic_memories SET scope='tenant',owner_user_id=NULL,status='active',"
                "reviewed_by=%s,reviewed_at=now(),updated_at=now() "
                "WHERE tenant_id=%s AND memory_id=%s AND scope='tenant' "
                "AND owner_user_id IS NULL AND status='pending'",
                (identity.user_id, identity.tenant_id, memory_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(409, "情景记忆不可审批")
            cursor.execute(
                "INSERT INTO memory.audit_events "
                "(tenant_id,event_id,actor_user_id,actor_type,action,resource_type,resource_id,details,expires_at) "
                "VALUES (%s,%s,%s,'user','episode.approve','episodic',%s,'{}',now()+interval '365 days')",
                (identity.tenant_id, uuid4(), identity.user_id, str(memory_id)),
            )

    @staticmethod
    def _require_admin(identity):
        if not identity.is_admin:
            raise HTTPException(403, "需要 tenant_admin 角色")

    @staticmethod
    def _require_prompt_key(prompt_key):
        if prompt_key not in PROMPT_KEYS:
            raise HTTPException(404, "prompt_key 不存在")

    def close(self):
        self.pool.close()

    def health(self):
        try:
            with self.pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() is not None
        except Exception:
            return False


def configured_memory_service(embeddings=None):
    from src.config import (
        DATABASE_URL,
        EPISODIC_MEMORY_ENABLED,
        MEMORY_READ_ENABLED,
        MEMORY_WRITE_ENABLED,
        PROCEDURAL_MEMORY_ENABLED,
        SEMANTIC_MEMORY_ENABLED,
    )

    if not DATABASE_URL:
        return NullMemoryService()
    if embeddings is None and MEMORY_READ_ENABLED and (
        SEMANTIC_MEMORY_ENABLED or EPISODIC_MEMORY_ENABLED
    ):
        from src.embeddings.dashscope_emb import DashScopeEmbeddings

        embeddings = DashScopeEmbeddings()
    return MemoryService(
        DATABASE_URL,
        embeddings=embeddings,
        read_enabled=MEMORY_READ_ENABLED,
        write_enabled=MEMORY_WRITE_ENABLED,
        semantic_enabled=SEMANTIC_MEMORY_ENABLED,
        episodic_enabled=EPISODIC_MEMORY_ENABLED,
        procedural_enabled=PROCEDURAL_MEMORY_ENABLED,
    )


def validate_prompt_overlay(content):
    """程序记忆只能追加业务表达规则，不能覆盖安全边界。"""
    content = content.strip()
    forbidden = ("tenant_id", "user_id", "RLS", "工具权限", "输出 schema", "忽略以上")
    if not content or len(content) > 4000 or any(word.lower() in content.lower() for word in forbidden):
        raise ValueError("程序提示候选违反安全约束")
    return content


def content_hash(content):
    return hashlib.sha256(content.encode()).digest()
