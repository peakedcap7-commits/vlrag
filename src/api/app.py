from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request

from src.api.runtime import ApiRuntimeManager, RuntimeResources
from src.api.schemas import (
    AssistantMessageRequest,
    AssistantMessageResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    MemoryListResponse,
    PromptActionResponse,
    PromptActivateRequest,
    PromptOptimizeRequest,
    PromptRollbackRequest,
    ReadyResponse,
    RecommendRequest,
    RecommendResponse,
)
from src.assistant_graph import build_assistant_graph
from src.config import ENABLE_MODEL_WARMUP
from src.memory import configured_memory_service
from src.outfit_advice_service import build_outfit_advice_service
from src.outfit_analyze_service import build_outfit_analyze_service
from src.outfit_revise_advice_service import (
    build_outfit_revise_advice_service,
)
from src.outfit_revise_candidate_service import (
    OutfitReviseCandidateService,
)
from src.outfit_revise_graph_service import OutfitReviseGraphService
from src.outfit_revise_service import OutfitReviseService
from src.performance import measure
from src.polyvore_recommend_service import build_polyvore_recommend_service
from src.polyvore_retrieval import retrieve_polyvore_text_candidates


def create_app(
    service=None,
    config=None,
    assistant_graph=None,
    outfit_analyze_service=None,
    outfit_advice_service=None,
    outfit_revise_service=None,
    outfit_revise_candidate_service=None,
    outfit_revise_graph_service=None,
    outfit_revise_advice_service=None,
    runtime_manager=None,
    enable_model_warmup=None,
    authenticator=None,
    memory_service=None,
):
    """创建仅负责 HTTP 边界的 FastAPI 应用。"""
    if runtime_manager is not None and service is not None:
        raise ValueError("runtime_manager 与 service 不能同时传入")

    owns_runtime = runtime_manager is None and service is None
    owns_memory = memory_service is None
    memory_service = memory_service or configured_memory_service()
    auto_warmup = (
        ENABLE_MODEL_WARMUP
        if enable_model_warmup is None
        else enable_model_warmup
    )
    revise_service = outfit_revise_service or OutfitReviseService()

    def build_resources():
        polyvore_service = build_polyvore_recommend_service(config)
        analyze_service = (
            outfit_analyze_service
            or build_outfit_analyze_service(
                image_embeddings=polyvore_service.image_embeddings,
                chroma_client=polyvore_service.chroma_client,
                resolver=polyvore_service.resolver,
                outfit_provider=polyvore_service.outfit_provider,
            )
        )
        advice_service = (
            outfit_advice_service or build_outfit_advice_service()
        )
        candidate_service = (
            outfit_revise_candidate_service
            or OutfitReviseCandidateService(
                retrieval=lambda query, limit: (
                    retrieve_polyvore_text_candidates(
                        query,
                        polyvore_service.chroma_client,
                        polyvore_service.text_embeddings,
                        limit,
                    )
                ),
                resolver=polyvore_service.resolver,
            )
        )
        graph_service = (
            outfit_revise_graph_service
            or OutfitReviseGraphService(polyvore_service.outfit_provider)
        )
        revise_advice_service = (
            outfit_revise_advice_service
            or build_outfit_revise_advice_service()
        )
        return RuntimeResources(
            polyvore_service=polyvore_service,
            assistant_graph=(
                assistant_graph
                or build_assistant_graph(
                    polyvore_service,
                    analyze_service,
                    advice_service,
                    revise_service,
                    candidate_service,
                    graph_service,
                    revise_advice_service,
                )
            ),
        )

    if runtime_manager is None:
        if service is None:
            runtime_manager = ApiRuntimeManager(build_resources)
        else:
            runtime_manager = ApiRuntimeManager(
                builder=lambda: None,
                resources=RuntimeResources(
                    polyvore_service=service,
                    assistant_graph=(
                        assistant_graph
                        or build_assistant_graph(
                            service,
                            outfit_analyze_service,
                            outfit_advice_service,
                            revise_service,
                            outfit_revise_candidate_service,
                            outfit_revise_graph_service,
                            outfit_revise_advice_service,
                        )
                    ),
                ),
            )

    @asynccontextmanager
    async def lifespan(app):
        if auto_warmup:
            runtime_manager.warmup()
        try:
            yield
        finally:
            if owns_runtime:
                runtime_manager.close()
            if owns_memory:
                memory_service.close()

    app = FastAPI(lifespan=lifespan)
    app.state.runtime_manager = runtime_manager
    app.state.authenticator = authenticator
    app.state.memory_service = memory_service

    def identity(request):
        auth = request.app.state.authenticator
        if auth is None:
            if not request.headers.get("Authorization", "").lower().startswith("bearer "):
                raise HTTPException(
                    401,
                    "缺少 Bearer 令牌",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            from src.auth import configured_authenticator

            try:
                auth = configured_authenticator()
            except ValueError as exc:
                raise HTTPException(503, "本地认证未配置") from exc
            request.app.state.authenticator = auth
        return auth.authenticate(request)

    def memories(request):
        service = request.app.state.memory_service
        if not service.enabled:
            raise HTTPException(503, "记忆数据库未配置")
        return service

    @app.middleware("http")
    async def record_request_duration(request, call_next):
        with measure(
            "total_ms",
            method=request.method,
            path=request.url.path,
        ):
            return await call_next(request)

    @app.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok"}

    @app.get("/health/ready", response_model=ReadyResponse)
    def ready(request: Request):
        result = request.app.state.runtime_manager.snapshot()
        result["postgres_ready"] = request.app.state.memory_service.health()
        return result

    @app.post("/warmup", response_model=ReadyResponse)
    def warmup(request: Request):
        current = identity(request)
        if not current.is_admin:
            raise HTTPException(403, "需要 tenant_admin 角色")
        result = request.app.state.runtime_manager.warmup()
        result["postgres_ready"] = request.app.state.memory_service.health()
        return result

    @app.post("/polyvore/recommend", response_model=RecommendResponse)
    def recommend(payload: RecommendRequest, request: Request):
        identity(request)
        resources = request.app.state.runtime_manager.get_resources()
        return resources.polyvore_service.recommend(
            payload.query,
            payload.top_k,
            payload.retrieval_limit,
        )

    @app.post("/assistant/message", response_model=AssistantMessageResponse)
    def assistant_message(payload: AssistantMessageRequest, request: Request):
        current = identity(request)
        resources = request.app.state.runtime_manager.get_resources()
        memory = request.app.state.memory_service
        graph_payload = payload.model_dump(mode="json", exclude_none=True)
        thread_id = graph_payload.pop("thread_id")
        if "conversation_state" not in graph_payload:
            stored = memory.load_thread(current, thread_id)
            if stored is not None:
                graph_payload["conversation_state"] = stored
        context = memory.load_context(
            current,
            graph_payload.get("message", ""),
            ("outfit_analyze", "outfit_revise"),
        )
        graph_payload["memory_context"] = {
            "semantic": context["semantic"],
            "episodic": context["episodic"],
        }
        graph_payload["procedural_prompts"] = context["procedural"]
        state = resources.assistant_graph.invoke(graph_payload)
        run_id = memory.record_run(current, thread_id, graph_payload, state)
        return {
            "thread_id": thread_id,
            "run_id": run_id,
            "intent": state["intent"],
            "status": state["status"],
            "result": state.get("result"),
            "message": state["response_message"],
        }

    @app.post("/assistant/feedback", response_model=FeedbackResponse)
    def feedback(payload: FeedbackRequest, request: Request):
        current = identity(request)
        feedback_id = memories(request).add_feedback(current, payload)
        return {"feedback_id": feedback_id, "accepted": True}

    @app.get("/assistant/memories", response_model=MemoryListResponse)
    def list_memories(request: Request, type: str):
        current = identity(request)
        if type not in {"semantic", "episodic"}:
            raise HTTPException(422, "type 只能是 semantic 或 episodic")
        items = memories(request).list_memories(current, type)
        return {"type": type, "items": items}

    @app.delete("/assistant/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: UUID, request: Request):
        current = identity(request)
        memories(request).delete_memory(current, memory_id)

    @app.post("/admin/prompts/{prompt_key}/optimize", response_model=PromptActionResponse)
    def optimize_prompt(prompt_key: str, payload: PromptOptimizeRequest, request: Request):
        current = identity(request)
        job_id = memories(request).optimize_prompt(
            current, prompt_key, payload.run_ids
        )
        return {"status": "queued", "job_id": job_id}

    @app.get("/admin/prompts/{prompt_key}/versions")
    def prompt_versions(prompt_key: str, request: Request):
        current = identity(request)
        return memories(request).list_prompt_versions(current, prompt_key)

    @app.post("/admin/prompts/{prompt_key}/versions/{version_id}/approve", response_model=PromptActionResponse)
    def approve_prompt(prompt_key: str, version_id: UUID, request: Request):
        current = identity(request)
        memories(request).approve_prompt(current, prompt_key, version_id)
        return {"status": "approved"}

    @app.post("/admin/prompts/{prompt_key}/versions/{version_id}/activate", response_model=PromptActionResponse)
    def activate_prompt(
        prompt_key: str,
        version_id: UUID,
        payload: PromptActivateRequest,
        request: Request,
    ):
        current = identity(request)
        result = memories(request).activate_prompt(
            current, prompt_key, version_id, payload.expected_generation
        )
        return {"status": "active", "generation": result["generation"]}

    @app.post("/admin/prompts/{prompt_key}/rollback", response_model=PromptActionResponse)
    def rollback_prompt(prompt_key: str, payload: PromptRollbackRequest, request: Request):
        current = identity(request)
        result = memories(request).activate_prompt(
            current, prompt_key, payload.version_id, payload.expected_generation, rollback=True
        )
        return {"status": "active", "generation": result["generation"]}

    @app.post("/admin/episodes/{memory_id}/approve", response_model=PromptActionResponse)
    def approve_episode(memory_id: UUID, request: Request):
        current = identity(request)
        memories(request).approve_episode(current, memory_id)
        return {"status": "approved"}

    return app


app = create_app()
