"""使用 PostgreSQL job 和 LangMem Core API 的单进程 worker。"""

import argparse
import json
import logging
import re
import time
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.auth import Identity
from src.memory import MemoryService, _vector, content_hash, validate_prompt_overlay

logger = logging.getLogger("shopping_qna.memory_worker")

SENSITIVE_TEXT = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://\S+|"
    r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b|"
    r"(?<!\d)1\d{10}(?!\d))"
)


def _redact(value):
    return SENSITIVE_TEXT.sub("[已脱敏]", value)


class PreferenceMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: str
    value: str = Field(min_length=1, max_length=100)
    polarity: int = Field(ge=-1, le=1)
    context: str | None = Field(default=None, max_length=500)
    confidence: float = Field(ge=0, le=1)


class EpisodeMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation: str = Field(min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=1000)
    result: str = Field(min_length=1, max_length=1000)


def _contents(output, schema):
    result = []
    for item in output:
        content = getattr(item, "content", item)
        if isinstance(content, tuple) and len(content) >= 3:
            content = content[2]
        if isinstance(content, BaseModel):
            content = content.model_dump()
        try:
            result.append(schema.model_validate(content))
        except Exception:
            continue
    return result


class MemoryWorker:
    def __init__(self, memory, poller_url, worker_id=None, llm=None):
        import psycopg
        from langmem import create_memory_manager, create_prompt_optimizer

        if llm is None:
            from src.llm.dashscope_client import build_chat_llm

            llm = build_chat_llm(temperature=0.1, timeout=30, max_retries=1)
        self.memory = memory
        self.poller_url = poller_url
        self.worker_id = worker_id or uuid4()
        self._connect = psycopg.connect
        self.semantic_manager = create_memory_manager(
            llm,
            schemas=[PreferenceMemory],
            instructions=(
                "只抽取用户明确表达且可长期复用的穿搭偏好。dimension 只能为 "
                "color/style/category/scene/constraint；polarity 只能为 -1 或 1。"
                "忽略临时指令、敏感信息、商品标识、图片键和推测。"
            ),
            enable_updates=False,
            enable_deletes=False,
        )
        self.episode_manager = create_memory_manager(
            llm,
            schemas=[EpisodeMemory],
            instructions=(
                "仅从带正向反馈的轨迹提取成功案例，保存可审计的 observation/action/result；"
                "不要输出隐藏推理、标识符或敏感信息。"
            ),
            enable_updates=False,
            enable_deletes=False,
        )
        self.optimizer = create_prompt_optimizer(llm, kind="prompt_memory")

    def claim(self):
        with self._connect(self.poller_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM memory.claim_memory_job(%s)", (self.worker_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                names = [item.name for item in cursor.description]
                return dict(zip(names, row))

    def run_once(self):
        job = self.claim()
        if job is None:
            return False
        identity = Identity(
            tenant_id=UUID(str(job["tenant_id"])),
            user_id=UUID(str(job["user_id"])) if job.get("user_id") else None,
            roles=frozenset(),
        )
        try:
            {
                "semantic_extract": self._semantic,
                "episodic_extract": self._episodic,
                "procedural_optimize": self._procedural,
            }[job["job_type"]](identity, job)
        except Exception as exc:
            error_code = (
                re.sub(r"[^a-z0-9_]", "_", type(exc).__name__.lower())[:64]
                or "worker_error"
            )
            logger.error(
                json.dumps(
                    {
                        "event": "memory_job_failed",
                        "job_id": str(job["job_id"]),
                        "job_type": job["job_type"],
                        "error_code": error_code,
                    }
                )
            )
            self._finish(identity, job, error_code)
        else:
            self._finish(identity, job, None)
        return True

    def _finish(self, identity, job, error_code):
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            if error_code:
                cursor.execute(
                    "SELECT memory.retry_memory_job(%s,interval '5 seconds',3::integer) AS retried",
                    (job["job_id"],),
                )
                if cursor.fetchone()["retried"]:
                    return
            cursor.execute(
                "SELECT memory.complete_memory_job(%s,%s,%s) AS completed",
                (job["job_id"], "failed" if error_code else "done", error_code),
            )
            if not cursor.fetchone()["completed"]:
                raise RuntimeError("memory_job_completion_rejected")

    def _semantic(self, identity, job):
        payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
        message = str(payload.get("message", ""))[:2000]
        output = self.semantic_manager.invoke({"messages": [{"role": "user", "content": message}]})
        dimensions = {"color", "style", "category", "scene", "constraint"}
        values = [
            item.model_copy(
                update={
                    "value": _redact(item.value),
                    "context": _redact(item.context) if item.context else None,
                }
            )
            for item in _contents(output, PreferenceMemory)
            if item.dimension in dimensions
            and item.polarity in {-1, 1}
            and _redact(item.value) == item.value
        ]
        if not values:
            return
        vectors = self.memory.embeddings.embed_documents([f"{item.dimension} {item.value} {item.context or ''}" for item in values])
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            for item, embedding in zip(values, vectors):
                cursor.execute(
                    "INSERT INTO memory.semantic_memories "
                    "(tenant_id,memory_id,user_id,dimension,value,polarity,context,confidence,source_run_id,embedding,status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,'active') "
                    "ON CONFLICT (tenant_id,user_id,dimension,lower(value),polarity) WHERE status='active' "
                    "DO UPDATE SET context=EXCLUDED.context,confidence=EXCLUDED.confidence,"
                    "source_run_id=EXCLUDED.source_run_id,embedding=EXCLUDED.embedding,updated_at=now()",
                    (identity.tenant_id, uuid4(), identity.user_id, item.dimension, item.value.strip(), item.polarity, item.context, item.confidence, job.get("source_run_id"), _vector(embedding)),
                )

    def _episodic(self, identity, job):
        payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
        feedback_id = UUID(payload["feedback_id"])
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            cursor.execute(
                "SELECT r.request_summary,r.response_summary,f.feedback_id,f.event,f.rating,f.comment "
                "FROM memory.assistant_runs r JOIN memory.assistant_feedback f USING (tenant_id,run_id) "
                "JOIN memory.assistant_threads t USING (tenant_id,thread_id) "
                "WHERE r.tenant_id=%s AND r.run_id=%s AND t.user_id=%s AND f.feedback_id=%s "
                "AND (f.event IN ('accepted','saved','purchased','thumbs_up') "
                "OR (f.event='rating' AND f.rating>=4))",
                (
                    identity.tenant_id,
                    job["source_run_id"],
                    identity.user_id,
                    feedback_id,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError("source_run_missing")
        messages = [
            {"role": "user", "content": json.dumps(row["request_summary"], ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(row["response_summary"], ensure_ascii=False)},
            {"role": "user", "content": f"正向反馈：{row['event']} {row.get('comment') or ''}"},
        ]
        episodes = [
            item.model_copy(
                update={
                    "observation": _redact(item.observation),
                    "action": _redact(item.action),
                    "result": _redact(item.result),
                }
            )
            for item in _contents(
                self.episode_manager.invoke({"messages": messages}), EpisodeMemory
            )
        ]
        if not episodes:
            return
        vectors = self.memory.embeddings.embed_documents([f"{item.observation} {item.action} {item.result}" for item in episodes])
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            for item_index, (item, embedding) in enumerate(zip(episodes, vectors)):
                cursor.execute(
                    "INSERT INTO memory.episodic_memories "
                    "(tenant_id,memory_id,owner_user_id,scope,observation,action,result,source_run_id,"
                    "source_feedback_id,source_job_id,source_item_index,embedding,status,expires_at) "
                    "VALUES (%s,%s,%s,'user',%s,%s,%s,%s,%s,%s,%s,%s::vector,'active',now()+interval '180 days') "
                    "ON CONFLICT (tenant_id,source_job_id,scope,source_item_index) "
                    "WHERE source_job_id IS NOT NULL DO NOTHING",
                    (identity.tenant_id, uuid4(), identity.user_id, item.observation, item.action, item.result, job["source_run_id"], row["feedback_id"], job["job_id"], item_index, _vector(embedding)),
                )
        tenant_identity = Identity(identity.tenant_id, None, frozenset())
        with self.memory.transaction(tenant_identity, "worker", self.worker_id) as cursor:
            for item_index, (item, embedding) in enumerate(zip(episodes, vectors)):
                cursor.execute(
                    "INSERT INTO memory.episodic_memories "
                    "(tenant_id,memory_id,owner_user_id,scope,observation,action,result,source_run_id,"
                    "source_feedback_id,source_job_id,source_item_index,embedding,status,expires_at) "
                    "VALUES (%s,%s,NULL,'tenant',%s,%s,%s,%s,%s,%s,%s,%s::vector,'pending',now()+interval '180 days') "
                    "ON CONFLICT (tenant_id,source_job_id,scope,source_item_index) "
                    "WHERE source_job_id IS NOT NULL DO NOTHING",
                    (identity.tenant_id, uuid4(), item.observation, item.action, item.result, job["source_run_id"], row["feedback_id"], job["job_id"], item_index, _vector(embedding)),
                )

    def _procedural(self, identity, job):
        payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
        prompt_key = payload["prompt_key"]
        created_by = UUID(payload["created_by"])
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            cursor.execute(
                "SELECT * FROM memory.get_procedural_job_evidence(%s)",
                (job["job_id"],),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "SELECT * FROM memory.get_active_prompt(%s)",
                (prompt_key,),
            )
            current = cursor.fetchone()
        if not rows:
            raise ValueError("feedback_required")
        trajectories = [
            (
                [
                    {"role": "user", "content": json.dumps(row["request_summary"], ensure_ascii=False)},
                    {"role": "assistant", "content": json.dumps(row["response_summary"], ensure_ascii=False)},
                ],
                {
                    "event": row["feedback_event"],
                    "rating": row["feedback_rating"],
                },
            )
            for row in rows
        ]
        base = "保持简洁、基于已提供事实给出穿搭建议。当前请求优先于历史偏好。"
        candidate = self.optimizer.invoke({"trajectories": trajectories, "prompt": base})
        candidate = validate_prompt_overlay(str(candidate))
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            cursor.execute(
                "INSERT INTO memory.procedural_prompt_versions "
                "(tenant_id,prompt_key,version_id,parent_version_id,content,content_hash,status,"
                "evidence_summary,evaluation_metrics,created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s) "
                "ON CONFLICT (tenant_id,prompt_key,content_hash) DO NOTHING",
                (identity.tenant_id, prompt_key, uuid4(), current["version_id"] if current else None, candidate, content_hash(candidate), json.dumps({"feedback_count": len(rows)}), json.dumps({"deterministic_checks": "passed"}), created_by),
            )


def main():
    parser = argparse.ArgumentParser(description="运行 LangMem PostgreSQL worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    from src.config import (
        EPISODIC_MEMORY_ENABLED,
        MEMORY_POLLER_DATABASE_URL,
        MEMORY_READ_ENABLED,
        MEMORY_WORKER_DATABASE_URL,
        MEMORY_WORKER_ID,
        MEMORY_WRITE_ENABLED,
        PROCEDURAL_MEMORY_ENABLED,
        SEMANTIC_MEMORY_ENABLED,
    )
    from src.embeddings.dashscope_emb import DashScopeEmbeddings

    if not MEMORY_WORKER_DATABASE_URL or not MEMORY_POLLER_DATABASE_URL:
        parser.error("必须配置 MEMORY_WORKER_DATABASE_URL 和 MEMORY_POLLER_DATABASE_URL")
    memory = MemoryService(
        MEMORY_WORKER_DATABASE_URL,
        embeddings=DashScopeEmbeddings(),
        read_enabled=MEMORY_READ_ENABLED,
        write_enabled=MEMORY_WRITE_ENABLED,
        semantic_enabled=SEMANTIC_MEMORY_ENABLED,
        episodic_enabled=EPISODIC_MEMORY_ENABLED,
        procedural_enabled=PROCEDURAL_MEMORY_ENABLED,
    )
    worker = MemoryWorker(
        memory,
        MEMORY_POLLER_DATABASE_URL,
        UUID(MEMORY_WORKER_ID) if MEMORY_WORKER_ID else None,
    )
    try:
        while worker.run_once() or not args.once:
            if not args.once:
                time.sleep(args.poll_seconds)
    finally:
        memory.close()


if __name__ == "__main__":
    main()
