from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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


class ReadyResponse(StrictModel):
    warmed_up: bool
    status: Literal["not_ready", "warming", "ready", "error"]
    warmup_seconds: float | None
    error: str | None


AssistantIntent = Literal[
    "single_item_recommend",
    "outfit_analyze",
    "outfit_revise",
    "scene_outfit_generate",
    "unsupported",
]
EvidenceLevel = Literal["strong", "medium", "weak"]


class ConversationItemMetadata(StrictModel):
    item_id: str
    category: str = ""
    sub_category: str = ""
    colors: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)

    @field_validator("item_id")
    @classmethod
    def item_id_must_not_be_blank(cls, value):
        if not value.strip():
            raise ValueError("item_metadata.item_id 不能是空白字符串")
        return value.strip()


class ConversationState(StrictModel):
    anchor_item_id: str | None = None
    candidate_item_ids: list[str] = Field(default_factory=list)
    selected_item_ids: list[str] = Field(default_factory=list)
    locked_item_ids: list[str] = Field(default_factory=list)
    excluded_item_ids: list[str] = Field(default_factory=list)
    item_metadata: list[ConversationItemMetadata] = Field(default_factory=list)
    last_intent: AssistantIntent | None = None

    @field_validator("anchor_item_id")
    @classmethod
    def anchor_item_id_must_not_be_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("anchor_item_id 不能是空白字符串")
        return value.strip() if value is not None else None

    @field_validator(
        "candidate_item_ids",
        "selected_item_ids",
        "locked_item_ids",
        "excluded_item_ids",
    )
    @classmethod
    def item_ids_must_be_unique_and_nonblank(cls, value):
        normalized = [item_id.strip() for item_id in value]
        if any(not item_id for item_id in normalized):
            raise ValueError("商品 ID 列表不能包含空白值")
        if len(normalized) != len(set(normalized)):
            raise ValueError("商品 ID 列表不能包含重复值")
        return normalized

    @model_validator(mode="after")
    def locked_and_excluded_items_must_not_overlap(self):
        overlap = set(self.locked_item_ids) & set(self.excluded_item_ids)
        if overlap:
            raise ValueError("locked_item_ids 与 excluded_item_ids 不能重叠")
        metadata_ids = [item.item_id for item in self.item_metadata]
        if len(metadata_ids) != len(set(metadata_ids)):
            raise ValueError("item_metadata 不能包含重复 item_id")
        return self


class OutfitAnalyzeResult(StrictModel):
    verdict: str
    summary: str
    strengths: list[str]
    issues: list[str]
    suggestions: list[str]


class NormalizedConstraints(StrictModel):
    exclude_categories: list[str] = Field(default_factory=list)
    prefer_categories: list[str] = Field(default_factory=list)
    keep_categories: list[str] = Field(default_factory=list)
    prefer_colors: list[str] = Field(default_factory=list)
    prefer_styles: list[str] = Field(default_factory=list)
    rewrite_scope: Literal["partial", "full"]


class ReplacementCandidate(StrictModel):
    item_id: str
    object_key: str
    category: str
    sub_category: str
    colors: list[str]
    style: list[str]
    match_level: Literal["strong", "medium", "weak"] = "weak"
    reason: str = "符合基础条件，但当前数据中缺少明确搭配证据。"


class OutfitReviseResult(StrictModel):
    exclude_categories: list[str] = Field(default_factory=list)
    prefer_categories: list[str] = Field(default_factory=list)
    keep_items: list[str] = Field(default_factory=list)
    prefer_colors: list[str] = Field(default_factory=list)
    style_shift: Literal["more_formal", "more_casual"] | None = None
    rewrite_scope: Literal["partial", "full"]
    normalized_constraints: NormalizedConstraints | None = None
    bound_keep_item_ids: list[str] = Field(default_factory=list)
    bound_exclude_item_ids: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    replacement_candidates: list[ReplacementCandidate] = Field(
        default_factory=list
    )


class OutfitReviseAdviceResult(StrictModel):
    verdict: str
    summary: str
    changes: list[str]
    suggestions: list[str]


class AssistantMessageRequest(StrictModel):
    message: str = ""
    image_keys: list[str] = Field(default_factory=list, max_length=4)
    conversation_state: ConversationState | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    retrieval_limit: int = Field(default=5, ge=1, le=5)

    @field_validator("image_keys")
    @classmethod
    def image_keys_must_be_unique_and_nonblank(cls, value):
        """图片对象键必须非空且不能重复。"""
        normalized = [key.strip() for key in value]
        if any(not key for key in normalized):
            raise ValueError("image_keys 不能包含空值")
        if len(normalized) != len(set(normalized)):
            raise ValueError("image_keys 不能重复")
        return normalized


class AssistantMessageResponse(StrictModel):
    intent: AssistantIntent
    status: Literal["ok", "not_ready", "unsupported"]
    result: (
        RecommendResponse
        | OutfitAnalyzeResult
        | OutfitReviseResult
        | OutfitReviseAdviceResult
        | None
    )
    message: str
