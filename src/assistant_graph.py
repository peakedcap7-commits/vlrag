from enum import Enum
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class AssistantIntent(str, Enum):
    """统一助手第一阶段支持的意图。"""

    SINGLE_ITEM_RECOMMEND = "single_item_recommend"
    OUTFIT_ANALYZE = "outfit_analyze"
    OUTFIT_REVISE = "outfit_revise"
    SCENE_OUTFIT_GENERATE = "scene_outfit_generate"
    UNSUPPORTED = "unsupported"


class AssistantState(TypedDict, total=False):
    """LangGraph 内部编排状态，不承担 HTTP 校验。"""

    message: str
    image_keys: list[str]
    conversation_state: dict[str, Any] | None
    top_k: int
    retrieval_limit: int
    intent: AssistantIntent
    status: str
    result: dict[str, Any] | None
    response_message: str


REVISION_KEYWORDS = (
    "不要",
    "换成",
    "换掉",
    "保留",
    "更正式",
    "更休闲",
    "改成",
    "替换",
)
FULL_REWRITE_KEYWORDS = ("重新搭一套", "重搭一套", "全部替换", "整套重搭")
SCENE_KEYWORDS = ("通勤", "约会", "面试", "度假", "派对", "推荐一套", "整套")


def classify_intent(message, image_keys, conversation_state):
    """按稳定规则识别意图，不调用模型或外部服务。"""
    message = (message or "").strip()
    image_keys = image_keys or []
    if not message and not image_keys and not conversation_state:
        return AssistantIntent.UNSUPPORTED
    if len(image_keys) >= 2:
        return AssistantIntent.OUTFIT_ANALYZE
    if any(
        word in message
        for word in (*REVISION_KEYWORDS, *FULL_REWRITE_KEYWORDS)
    ):
        return AssistantIntent.OUTFIT_REVISE
    if any(word in message for word in SCENE_KEYWORDS):
        return AssistantIntent.SCENE_OUTFIT_GENERATE
    if message or len(image_keys) == 1:
        return AssistantIntent.SINGLE_ITEM_RECOMMEND
    return AssistantIntent.UNSUPPORTED


def classify_intent_node(state):
    """把输入映射为后续节点名称。"""
    return {
        "intent": classify_intent(
            state.get("message", ""),
            state.get("image_keys", []),
            state.get("conversation_state"),
        )
    }


def _not_ready(message):
    return {
        "status": "not_ready",
        "result": None,
        "response_message": message,
    }


def scene_generate_node(_state):
    """场景整套穿搭占位节点。"""
    return _not_ready("场景整套穿搭能力尚未接入。")


def unsupported_node(_state):
    """空输入或不支持请求的终止节点。"""
    return {
        "status": "unsupported",
        "result": None,
        "response_message": "请输入明确的商品或穿搭需求。",
    }


def build_assistant_graph(
    service,
    outfit_analyze_service=None,
    outfit_advice_service=None,
    outfit_revise_service=None,
    outfit_revise_candidate_service=None,
    outfit_revise_graph_service=None,
    outfit_revise_advice_service=None,
):
    """注入现有推荐 service，并编译无持久记忆的同步流程图。"""

    def single_item_recommend_node(state):
        message = state.get("message", "").strip()
        if not message:
            return _not_ready("单图推荐能力尚未接入。")
        return {
            "status": "ok",
            "result": service.recommend(
                message,
                state["top_k"],
                state["retrieval_limit"],
            ),
            "response_message": "推荐完成。",
        }

    def outfit_analyze_node(state):
        if outfit_analyze_service is None:
            return _not_ready("多件搭配图片匹配能力尚未接入。")
        if outfit_advice_service is None:
            return _not_ready("穿搭建议服务尚未接入。")
        analysis = outfit_analyze_service.analyze(state["image_keys"])
        return {
            "status": "ok",
            "result": outfit_advice_service.generate(analysis),
            "response_message": "穿搭分析完成。",
        }

    def outfit_revise_node(state):
        conversation_state = state.get("conversation_state")
        if not conversation_state:
            return _not_ready(
                "请先提供 conversation_state，才能继续改搭。"
            )
        if outfit_revise_service is None:
            return _not_ready("改搭约束解析服务尚未接入。")
        parsed = outfit_revise_service.parse(
            state.get("message", ""),
            conversation_state,
        )
        if parsed.get("needs_clarification"):
            parsed.setdefault("replacement_candidates", [])
            return {
                "status": "ok",
                "result": parsed,
                "response_message": parsed.get(
                    "clarification_question",
                    "请补充明确的改搭要求。",
                ),
            }
        if outfit_revise_candidate_service is None:
            return {
                "status": "ok",
                "result": parsed,
                "response_message": "已解析改搭约束，尚未执行真实商品替换。",
            }
        outcome = outfit_revise_candidate_service.find_replacements(
            state.get("message", ""),
            conversation_state,
            parsed,
            state["retrieval_limit"],
        )
        replacement_candidates = outcome["replacement_candidates"]
        if outfit_revise_graph_service is not None:
            replacement_candidates = (
                outfit_revise_graph_service.validate_and_rank(
                    replacement_candidates,
                    conversation_state,
                    parsed,
                    outcome.get("ranking_context", {}),
                )
            )
        result = dict(parsed)
        result["replacement_candidates"] = replacement_candidates
        if outfit_revise_advice_service is not None:
            result = outfit_revise_advice_service.generate(
                result,
                conversation_state,
            )
            response_message = "改搭建议生成完成。"
        else:
            response_message = outcome["message"]
        return {
            "status": "ok",
            "result": result,
            "response_message": response_message,
        }

    builder = StateGraph(AssistantState)
    builder.add_node("classify_intent_node", classify_intent_node)
    builder.add_node("single_item_recommend_node", single_item_recommend_node)
    builder.add_node("outfit_analyze_node", outfit_analyze_node)
    builder.add_node("outfit_revise_node", outfit_revise_node)
    builder.add_node("scene_generate_node", scene_generate_node)
    builder.add_node("unsupported_node", unsupported_node)
    builder.add_edge(START, "classify_intent_node")
    builder.add_conditional_edges(
        "classify_intent_node",
        lambda state: state["intent"],
        {
            AssistantIntent.SINGLE_ITEM_RECOMMEND: "single_item_recommend_node",
            AssistantIntent.OUTFIT_ANALYZE: "outfit_analyze_node",
            AssistantIntent.OUTFIT_REVISE: "outfit_revise_node",
            AssistantIntent.SCENE_OUTFIT_GENERATE: "scene_generate_node",
            AssistantIntent.UNSUPPORTED: "unsupported_node",
        },
    )
    for node_name in (
        "single_item_recommend_node",
        "outfit_analyze_node",
        "outfit_revise_node",
        "scene_generate_node",
        "unsupported_node",
    ):
        builder.add_edge(node_name, END)
    return builder.compile()
