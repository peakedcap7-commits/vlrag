from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """拒绝响应和请求中的额外字段。"""

    model_config = ConfigDict(extra="forbid")


class RecommendRequest(StrictModel):
    query: str
    top_k: int = Field(ge=1, le=50)
    retrieval_limit: int = Field(ge=1, le=5)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value):
        """拒绝空白查询。"""
        if not value.strip():
            raise ValueError("query 不能为空")
        return value


class ResolvedItem(StrictModel):
    found: bool
    item_id: str
    bucket: str
    object_key: str
    retrieval_text: str
    category: str
    sub_category: str
    colors: list[str]
    style: list[str]
    scene: list[str]


class Anchor(StrictModel):
    item_id: str
    object_key: str
    retrieval_text: str
    sources: list[str]
    rrf_score: float
    rule_score: float
    adjusted_score: float
    resolved: ResolvedItem


class OutfitCandidate(StrictModel):
    candidate_item_id: str
    shared_outfit_ids: list[str]
    cooccurrence_count: int
    resolved: ResolvedItem


class RecommendResponse(StrictModel):
    query: str
    anchor: Anchor | None
    outfit_candidates: list[OutfitCandidate]


class HealthResponse(StrictModel):
    status: str
