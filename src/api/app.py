from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.api.schemas import (
    AssistantMessageRequest,
    AssistantMessageResponse,
    HealthResponse,
    ReadyResponse,
    RecommendRequest,
    RecommendResponse,
)
from src.api.runtime import ApiRuntimeManager, RuntimeResources
from src.assistant_graph import build_assistant_graph
from src.config import ENABLE_MODEL_WARMUP
from src.outfit_advice_service import build_outfit_advice_service
from src.outfit_analyze_service import build_outfit_analyze_service
from src.outfit_revise_service import OutfitReviseService
from src.outfit_revise_candidate_service import (
    OutfitReviseCandidateService,
)
from src.outfit_revise_graph_service import OutfitReviseGraphService
from src.outfit_revise_advice_service import (
    build_outfit_revise_advice_service,
)
from src.polyvore_retrieval import retrieve_polyvore_text_candidates
from src.polyvore_recommend_service import build_polyvore_recommend_service
from src.performance import measure


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
):
    """创建仅负责 HTTP 边界的 FastAPI 应用。"""
    if runtime_manager is not None and service is not None:
        raise ValueError("runtime_manager 与 service 不能同时传入")

    owns_runtime = runtime_manager is None and service is None
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

    app = FastAPI(lifespan=lifespan)
    app.state.runtime_manager = runtime_manager

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
        return request.app.state.runtime_manager.snapshot()

    @app.post("/warmup", response_model=ReadyResponse)
    def warmup(request: Request):
        return request.app.state.runtime_manager.warmup()

    @app.post("/polyvore/recommend", response_model=RecommendResponse)
    def recommend(payload: RecommendRequest, request: Request):
        resources = request.app.state.runtime_manager.get_resources()
        return resources.polyvore_service.recommend(
            payload.query,
            payload.top_k,
            payload.retrieval_limit,
        )

    @app.post("/assistant/message", response_model=AssistantMessageResponse)
    def assistant_message(payload: AssistantMessageRequest, request: Request):
        resources = request.app.state.runtime_manager.get_resources()
        state = resources.assistant_graph.invoke(payload.model_dump())
        return {
            "intent": state["intent"],
            "status": state["status"],
            "result": state.get("result"),
            "message": state["response_message"],
        }

    return app


app = create_app()
