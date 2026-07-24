import json
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from src.performance import log_performance, measure


class OutfitAdvicePayload(BaseModel):
    """约束文本 LLM 只能返回用户可读建议字段。"""

    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    strengths: list[str]
    issues: list[str]
    suggestions: list[str]


def _public_facts(analysis):
    """裁剪内部技术结果，避免向 LLM 传递图数据库标识。"""
    return {
        "score": analysis["score"],
        "evidence_level": analysis["evidence_level"],
        "graph_pair_count": len(analysis["graph_evidence"]),
        "total_cooccurrence": sum(
            evidence["cooccurrence_count"]
            for evidence in analysis["graph_evidence"]
        ),
        "rule_scores": analysis["rule_scores"],
        "warnings": analysis["warnings"],
        "items": [
            {
                "category": item["matches"][0]["category"],
                "sub_category": item["matches"][0]["sub_category"],
                "colors": item["matches"][0]["colors"],
                "style": item["matches"][0]["style"],
            }
            for item in analysis["items"]
        ],
    }


def _parse_json_content(content):
    """兼容模型偶尔返回的 Markdown JSON 代码块。"""
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        content = "\n".join(lines)
    return json.loads(content)


class OutfitAdviceService:
    """把内部评分事实转换为面向用户的穿搭建议。"""

    def __init__(self, llm):
        self.llm = llm

    def generate(self, analysis):
        facts = json.dumps(
            _public_facts(analysis),
            ensure_ascii=False,
        )
        prompt = f"""
你是穿搭建议助手。请严格依据下列分析事实生成简洁中文建议，不得编造品牌、价格、材质或未提供的图片属性。

分析事实：
{facts}

只返回一个 JSON 对象，字段必须且只能包含：
- verdict：一句简短结论
- summary：一到两句整体说明
- strengths：优点字符串数组
- issues：问题字符串数组，没有则为空数组
- suggestions：可执行建议字符串数组
不要输出 Markdown、解释或技术字段。
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
            with measure("llm_ms", operation="outfit_analyze"):
                response = self.llm.invoke(prompt)
            try:
                result = OutfitAdvicePayload.model_validate(
                    _parse_json_content(response.content)
                ).model_dump()
            except Exception:
                parse_failed = True
                repair_used = True
                attempts += 1
                repair_prompt = f"""
只修复 JSON 格式，使下面内容满足原有字段要求。
不得修改、增加或删除原有语义，不得输出 Markdown 或解释。

待修复内容：
{response.content}
""".strip()
                with measure("llm_ms", operation="outfit_analyze_repair"):
                    repaired = self.llm.invoke(repair_prompt)
                result = OutfitAdvicePayload.model_validate(
                    _parse_json_content(repaired.content)
                ).model_dump()
            success = True
        except Exception as exc:
            error_type = type(exc).__name__
            fallback_used = True
            result = _fallback_advice(analysis)
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
                operation="outfit_analyze",
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


def _fallback_advice(analysis):
    """仅用既有评分事实生成保守建议，不补充未知属性。"""
    evidence_level = analysis.get("evidence_level", "weak")
    verdicts = {
        "strong": "当前搭配具备较明确的协调依据",
        "medium": "当前搭配可以作为参考",
        "weak": "当前搭配建议谨慎调整",
    }
    summaries = {
        "strong": "现有分析支持当前组合，可先保留整体方向。",
        "medium": "现有分析提供了部分支持，建议从小范围调整开始。",
        "weak": "现有信息不足以给出确定结论，建议优先检查品类、颜色和风格。",
    }
    return {
        "verdict": verdicts.get(evidence_level, verdicts["weak"]),
        "summary": summaries.get(evidence_level, summaries["weak"]),
        "strengths": (
            ["当前组合具备一定协调性"]
            if evidence_level in {"strong", "medium"}
            else []
        ),
        "issues": (
            ["当前可参考的搭配信息有限"]
            if evidence_level == "weak"
            else []
        ),
        "suggestions": ["可根据已识别的品类、颜色和风格做小幅调整。"],
    }


def build_outfit_advice_service():
    """组装轻量文本模型，不调用视觉模型。"""
    from src.config import QWEN_TURBO
    from src.llm.dashscope_client import build_chat_llm

    return OutfitAdviceService(
        build_chat_llm(
            model=QWEN_TURBO,
            temperature=0.2,
            timeout=12,
            max_retries=1,
        )
    )
