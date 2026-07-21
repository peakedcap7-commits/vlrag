from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.api.schemas import HealthResponse, RecommendRequest, RecommendResponse
from src.polyvore_recommend_service import build_polyvore_recommend_service


def create_app(service=None, config=None):
    """创建仅负责 HTTP 边界的 FastAPI 应用。"""
    @asynccontextmanager
    async def lifespan(app):
        if service is None:
            app.state.polyvore_service = build_polyvore_recommend_service(config)
        yield

    app = FastAPI(lifespan=lifespan)
    if service is not None:
        app.state.polyvore_service = service

    @app.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok"}

    @app.post("/polyvore/recommend", response_model=RecommendResponse)
    def recommend(payload: RecommendRequest, request: Request):
        return request.app.state.polyvore_service.recommend(
            payload.query,
            payload.top_k,
            payload.retrieval_limit,
        )

    return app


app = create_app()
