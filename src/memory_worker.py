"""使用 PostgreSQL job 和 LangMem Core API 的单进程 worker。"""

import argparse
import json
import logging
import os
import re
import time
from typing import Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from src.auth import Identity
from src.memory import MemoryService, _vector, content_hash, validate_prompt_overlay
from src.memory_events import audit, cap_memories, lock_owner

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
    evidence: str = Field(default='', max_length=500)
    durability: Literal['explicit', 'inferred', 'temporary'] = 'inferred'
    sensitive: bool = False


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
        self.maintenance_url = os.getenv('MEMORY_MAINTENANCE_DATABASE_URL', '')
        self._next_maintenance = 0.0
        self.semantic_manager = create_memory_manager(
            llm,
            schemas=[PreferenceMemory],
            instructions=(
                "提取用户可长期复用的穿搭偏好。dimension 只能为 "
                "color/style/category/scene/constraint；polarity 只能为 -1 或 1。"
                "evidence逐字引用用户原话，durability区分explicit明确长期偏好、inferred推断、temporary临时指令。"
                "尺码、身体特征、预算标记sensitive=true；忽略联系方式、商品标识和图片键。"
                "参考existing更新冲突偏好，保留其ID；只返回本次新增或改变的记忆。"
            ),
            enable_updates=True,
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
        self.maintain()
        job = self.claim()
        if job is None:
            return False
        identity = Identity(
            tenant_id=UUID(str(job["tenant_id"])),
            user_id=UUID(str(job["user_id"])) if job.get("user_id") else None,
            roles=frozenset(),
        )
        try:
            enabled, handler = {
                'semantic_extract': (self.memory.semantic_enabled, self._semantic),
                'episodic_extract': (self.memory.episodic_enabled, self._episodic),
                'procedural_optimize': (self.memory.procedural_enabled, self._procedural),
            }[job['job_type']]
            if self.memory.write_enabled and enabled:
                handler(identity, job)
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

    def maintain(self):
        if not self.maintenance_url or time.monotonic() < self._next_maintenance:
            return
        try:
            with self._connect(self.maintenance_url) as connection, connection.cursor() as cursor:
                cursor.execute('SELECT memory.run_memory_maintenance()')
            self._next_maintenance = time.monotonic() + 86400
        except Exception as exc:
            logger.warning('memory_maintenance_failed error_type=%s', type(exc).__name__)
            self._next_maintenance = time.monotonic() + 300

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
        with self.memory.transaction(identity, "worker", self.worker_id) as cursor:
            cursor.execute("SELECT memory_id,dimension,value,polarity,context,confidence,revision FROM memory.semantic_memories "
                           "WHERE tenant_id=%s AND user_id=%s AND status='active' AND (expires_at IS NULL OR expires_at>now()) "
                           "ORDER BY updated_at DESC LIMIT 100", (identity.tenant_id,identity.user_id))
            existing = {str(row['memory_id']):row for row in cursor.fetchall()}
        output = self.semantic_manager.invoke({
            'messages':[{'role':'user','content':message}],
            'existing':[(key,'PreferenceMemory',{k:v for k,v in row.items() if k not in ('memory_id','revision')})
                        for key,row in existing.items()]})
        for extracted in output:
            values = _contents([extracted], PreferenceMemory)
            if not values:
                continue
            item = values[0]
            if item.dimension not in {'color','style','category','scene','constraint'} or item.polarity not in {-1,1}:
                continue
            if item.durability == 'temporary' or _redact(item.value) != item.value:
                continue
            if re.search(r'今天|这次|本次|明天|暂时', message) and not re.search(r'一直|长期|平时|通常|以后|记住', message):
                continue
            old = existing.get(str(getattr(extracted,'id','')))
            if old is None:
                # 精确反转无需模型猜ID；只有本次读到的记录能成为前版本。
                old = next((r for r in existing.values() if r['dimension']==item.dimension
                            and r['value'].casefold()==item.value.strip().casefold()),None)
            if old and all(old[k]==getattr(item,k) for k in ('dimension','value','polarity','context')):
                continue
            sensitive = item.sensitive or bool(re.search(r'尺码|身高|体重|胸围|腰围|臀围|预算|收入',item.value+' '+(item.context or '')+' '+message))
            explicit = item.durability=='explicit' and bool(item.evidence) and item.evidence in message
            pending = sensitive or not explicit
            vector = None if pending else _vector(self.memory.embeddings.embed_query(f'{item.dimension} {item.value} {item.context or ""}'))
            # 重放ID依赖候选内容，不依赖模型返回顺序。
            memory_id = uuid5(UUID(str(job['job_id'])),json.dumps(
                [item.dimension,item.value.strip(),item.polarity,item.context],ensure_ascii=False))
            with self.memory.transaction(identity,'worker',self.worker_id) as cursor:
                lock_owner(cursor,identity)
                cursor.execute('SELECT 1 FROM memory.semantic_memories WHERE tenant_id=%s AND memory_id=%s', (identity.tenant_id,memory_id))
                if cursor.fetchone():
                    continue
                previous_revision = None
                if old:
                    cursor.execute("SELECT revision FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s AND memory_id=%s "
                                   "AND revision=%s AND status='active' AND (expires_at IS NULL OR expires_at>now())",
                                   (identity.tenant_id,identity.user_id,old['memory_id'],old['revision']))
                    if not cursor.fetchone():
                        raise ValueError('semantic_existing_changed')
                    previous_revision = old['revision']
                    if not pending:
                        cursor.execute("UPDATE memory.semantic_memories SET status='superseded',embedding=NULL,deleted_at=now(),updated_at=now() "
                                       "WHERE tenant_id=%s AND memory_id=%s RETURNING revision",(identity.tenant_id,old['memory_id']))
                        previous_revision = cursor.fetchone()['revision']
                else:
                    cursor.execute("SELECT 1 FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s AND dimension=%s "
                                   "AND lower(value)=lower(%s) AND status='active'",(identity.tenant_id,identity.user_id,item.dimension,item.value.strip()))
                    if cursor.fetchone():
                        raise ValueError('semantic_concurrent_insert')
                cursor.execute(
                    "INSERT INTO memory.semantic_memories "
                    "(tenant_id,memory_id,user_id,dimension,value,polarity,context,confidence,source_run_id,embedding,status,supersedes_memory_id,expires_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,CASE WHEN %s THEN now()+interval '7 days' ELSE NULL END)",
                    (identity.tenant_id,memory_id,identity.user_id,item.dimension,item.value.strip(),item.polarity,
                     _redact(item.context) if item.context else None,item.confidence,job.get('source_run_id'),vector,
                     'pending' if pending else 'active',old['memory_id'] if old else None,pending))
                cursor.execute("INSERT INTO memory.memory_events(tenant_id,event_id,user_id,kind,semantic_memory_id,expected_memory_revision,"
                               "expected_previous_revision,summary,reversible_until,expires_at) "
                               "VALUES(%s,%s,%s,%s,%s,1,%s,%s,CASE WHEN %s THEN NULL ELSE now()+interval '7 days' END,now()+interval '7 days')",
                               (identity.tenant_id,uuid5(memory_id,'event'),identity.user_id,
                                'semantic_confirmation_required' if pending else 'semantic_saved',memory_id,previous_revision,
                                ('偏好：' if item.polarity>0 else '不偏好：')+item.value,pending))
                audit(cursor,identity,'memory.propose' if pending else 'memory.save',memory_id,'worker')
                cap_memories(cursor,identity)

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
                    "WHERE source_job_id IS NOT NULL DO NOTHING RETURNING memory_id",
                    (identity.tenant_id, uuid4(), identity.user_id, item.observation, item.action, item.result, job["source_run_id"], row["feedback_id"], job["job_id"], item_index, _vector(embedding)),
                )
                inserted = cursor.fetchone()
                if inserted:
                    cursor.execute("INSERT INTO memory.memory_events(tenant_id,event_id,user_id,kind,episodic_memory_id,summary,reversible_until,expires_at) "
                                   "VALUES(%s,%s,%s,'episodic_saved',%s,%s,now()+interval '7 days',now()+interval '7 days')",
                                   (identity.tenant_id,uuid4(),identity.user_id,inserted['memory_id'],item.result))
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
