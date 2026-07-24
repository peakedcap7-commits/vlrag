import json
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from src.performance import log_performance, measure


class OutfitReviseAdvicePayload(BaseModel):
    """约束文本 LLM 只能返回用户可读的改搭建议。"""

    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    changes: list[str]
    suggestions: list[str]


def _parse_json_content(content):
    """兼容模型偶尔返回的 Markdown JSON 代码块。"""
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        content = "\n".join(lines)
    return json.loads(content)


def _describe_item(item):
    """把商品元数据转换为不含内部标识的用户描述。"""
    color = (item.get("colors") or [""])[0]
    category = item.get("sub_category") or item.get("category") or "单品"
    return f"当前{color}{category}"


def _item_descriptions(conversation_state):
    """按商品标识建立仅供内部替换使用的用户描述。"""
    return {
        str(item["item_id"]): _describe_item(item)
        for item in conversation_state.get("item_metadata", [])
        if item.get("item_id")
    }


def _retained_descriptions(revise_result, conversation_state):
    """将保留商品绑定转换为用户可读描述，不向模型传递标识。"""
    descriptions = _item_descriptions(conversation_state)
    retained_ids = dict.fromkeys(
        item_id
        for item_id in [
            *conversation_state.get("locked_item_ids", []),
            *revise_result.get("bound_keep_item_ids", []),
            conversation_state.get("anchor_item_id"),
        ]
        if item_id
    )
    return list(
        dict.fromkeys(
            descriptions.get(str(item_id), "已保留单品")
            for item_id in retained_ids
        )
    )


def _public_facts(revise_result, conversation_state):
    """仅向文本模型提供表达建议所需的确定性事实。"""
    return {
        "constraints": {
            "exclude_categories": revise_result.get(
                "exclude_categories",
                [],
            ),
            "prefer_categories": revise_result.get(
                "prefer_categories",
                [],
            ),
            "keep_items": revise_result.get("keep_items", []),
            "prefer_colors": revise_result.get("prefer_colors", []),
            "style_shift": revise_result.get("style_shift"),
            "rewrite_scope": revise_result.get("rewrite_scope"),
        },
        "retained_items": _retained_descriptions(
            revise_result,
            conversation_state,
        ),
        "current_items": list(
            dict.fromkeys(
                _item_descriptions(conversation_state).values()
            )
        ),
        "replacement_candidates": [
            {
                "category": candidate.get("category", ""),
                "sub_category": candidate.get("sub_category", ""),
                "colors": candidate.get("colors", []),
                "style": candidate.get("style", []),
                "match_level": candidate.get("match_level", "weak"),
                "reason": candidate.get("reason", ""),
            }
            for candidate in revise_result.get(
                "replacement_candidates",
                [],
            )
        ],
    }


def _sanitize_advice(result, revise_result, conversation_state):
    """清理模型文本中的内部标识，避免技术信息进入公开响应。"""
    descriptions = _item_descriptions(conversation_state)
    replacements = {
        **{
            str(item_id): description
            for item_id, description in descriptions.items()
        },
        **{
            str(candidate.get("item_id")): "候选单品"
            for candidate in revise_result.get("replacement_candidates", [])
            if candidate.get("item_id")
        },
        **{
            str(candidate.get("object_key")): "候选单品"
            for candidate in revise_result.get("replacement_candidates", [])
            if candidate.get("object_key")
        },
    }
    for item_id in [
        *conversation_state.get("candidate_item_ids", []),
        *conversation_state.get("selected_item_ids", []),
        *conversation_state.get("locked_item_ids", []),
        *conversation_state.get("excluded_item_ids", []),
        *revise_result.get("bound_keep_item_ids", []),
        *revise_result.get("bound_exclude_item_ids", []),
        conversation_state.get("anchor_item_id"),
    ]:
        if item_id:
            replacements.setdefault(str(item_id), "已保留单品")

    technical_names = (
        "shared_outfit_ids",
        "object_key",
        "outfit_id",
        "graph_score",
        "rule_scores",
        "item_id",
    )

    def clean_text(text):
        for identifier, description in sorted(
            replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            text = text.replace(identifier, description)
        for name in technical_names:
            text = text.replace(name, "技术标识")
        return text

    return {
        key: (
            [clean_text(item) for item in value]
            if isinstance(value, list)
            else clean_text(value)
        )
        for key, value in result.items()
    }


class OutfitReviseAdviceService:
    """把已排序的改搭事实转换为用户友好建议。"""

    def __init__(self, llm):
        self.llm = llm

    def generate(self, revise_result, conversation_state):
        facts = json.dumps(
            _public_facts(revise_result, conversation_state),
            ensure_ascii=False,
        )
        prompt = f"""
你是穿搭改搭建议助手。请严格依据下列已确定事实生成简洁中文建议。
候选顺序已经由系统确定，你不得重新选择、删除、增加或调整候选顺序。
不得编造品牌、价格、材质、图片属性或图数据库证据。
不得输出商品 ID、对象键、穿搭关系标识或技术评分字段；
只能使用改搭事实中的用户描述。

改搭事实：
{facts}

只返回一个 JSON 对象，字段必须且只能包含：
- verdict：一句简短结论
- summary：一到两句整体说明
- changes：本次改搭变化字符串数组
- suggestions：可执行建议字符串数组
不要输出 Markdown、解释、商品 ID、对象键或任何技术字段。
""".strip()
        started_at = perf_counter()
        attempts = 0
        parse_failed = False
        repair_used = False
        success = False
        fallback_used = False
        error_type = None
        result = None
        try:
            attempts += 1
            with measure("llm_ms", operation="outfit_revise"):
                response = self.llm.invoke(prompt)
            try:
                result = OutfitReviseAdvicePayload.model_validate(
                    _parse_json_content(response.content)
                ).model_dump()
            except Exception:
                parse_failed = True
                repair_used = True
                attempts += 1
                repair_prompt = f"""
只修复 JSON 格式，使下面内容满足原有字段要求。
不得修改、增加或删除原有语义，不得输出 Markdown 或解释。
不得输出商品 ID、对象键、穿搭关系标识或技术评分字段。

待修复内容：
{response.content}
""".strip()
                with measure("llm_ms", operation="outfit_revise_repair"):
                    repaired = self.llm.invoke(repair_prompt)
                result = OutfitReviseAdvicePayload.model_validate(
                    _parse_json_content(repaired.content)
                ).model_dump()
            success = True
            result = _sanitize_advice(
                result,
                revise_result,
                conversation_state,
            )
        except Exception as exc:
            error_type = type(exc).__name__
            fallback_used = True
            result = _fallback_advice(revise_result, conversation_state)
        finally:
            total_ms = (perf_counter() - started_at) * 1000
            transport_retries = (
                int(getattr(self.llm, "max_retries", 0) or 0)
                if fallback_used and attempts == 1
                else 0
            )
            log_performance(
                "llm_total_ms",
                total_ms,
                operation="outfit_revise",
                llm_success=success,
                llm_attempt_count=attempts,
                llm_retry_count=max(
                    attempts - 1,
                    transport_retries,
                ),
                llm_parse_failed=parse_failed,
                llm_parse_repair_used=repair_used,
                fallback_used=fallback_used,
                error_type=error_type,
                llm_total_ms=round(total_ms, 3),
            )
        return result


def _fallback_advice(revise_result, conversation_state=None):
    """只依据既有约束和首个排序候选生成保守改搭建议。"""
    conversation_state = conversation_state or {}
    excluded = revise_result.get("exclude_categories", [])
    preferred = revise_result.get("prefer_categories", [])
    candidates = revise_result.get("replacement_candidates", [])
    changes = [
        *[f"减少使用{category}" for category in excluded],
        *[f"优先考虑{category}" for category in preferred],
    ]
    suggestions = []
    if candidates:
        candidate = candidates[0]
        description = "".join(
            [
                *(candidate.get("colors") or [])[:1],
                candidate.get("sub_category")
                or candidate.get("category", ""),
            ]
        )
        if description:
            suggestions.append(f"可优先尝试{description}。")
    if not suggestions:
        suggestions.append("可先按已确认的改搭方向逐项调整。")
    retained = _retained_descriptions(revise_result, conversation_state)
    retained_summary = "、".join(retained) if retained else "已保留单品"
    return {
        "verdict": (
            "已找到可参考的替换方向"
            if candidates
            else "暂未生成可靠的替换建议"
        ),
        "summary": (
            f"建议保留{retained_summary}，并按现有候选顺序逐一尝试。"
            if candidates
            else "当前没有足够候选，建议补充更明确的改搭条件。"
        ),
        "changes": changes,
        "suggestions": suggestions,
    }


def build_outfit_revise_advice_service():
    """组装 qwen-turbo 文本模型，不调用视觉模型。"""
    from src.config import QWEN_TURBO
    from src.llm.dashscope_client import build_chat_llm

    return OutfitReviseAdviceService(
        build_chat_llm(
            model=QWEN_TURBO,
            temperature=0.2,
            timeout=12,
            max_retries=1,
        )
    )
