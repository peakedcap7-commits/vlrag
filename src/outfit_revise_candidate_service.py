from src.outfit_revise_service import (
    normalize_categories,
    normalize_colors,
    normalize_styles,
)


STYLE_SHIFT_QUERY = {
    "more_formal": "正式",
    "more_casual": "休闲",
}


def _candidate_fields(resolved):
    return {
        "item_id": str(resolved["item_id"]),
        "object_key": resolved.get("object_key", ""),
        "category": resolved.get("category", ""),
        "sub_category": resolved.get("sub_category", ""),
        "colors": list(resolved.get("colors", [])),
        "style": list(resolved.get("style", [])),
    }


def _metadata_terms(candidate):
    category_text = (
        f"{candidate.get('category', '')} "
        f"{candidate.get('sub_category', '')}"
    )
    color_text = " ".join(candidate.get("colors", []))
    style_text = " ".join(candidate.get("style", []))
    return (
        set(normalize_categories(category_text)),
        set(normalize_colors(color_text)),
        set(normalize_styles(style_text)),
    )


class OutfitReviseCandidateService:
    """只读召回并过滤改搭候选，不执行搭配验证或数据写入。"""

    def __init__(self, retrieval, resolver):
        self.retrieval = retrieval
        self.resolver = resolver

    def find_replacements(
        self,
        message,
        conversation_state,
        parsed_constraints,
        limit,
    ):
        if parsed_constraints.get("needs_clarification"):
            return {
                "replacement_candidates": [],
                "message": parsed_constraints.get(
                    "clarification_question",
                    "请补充明确的改搭要求。",
                ),
            }

        prefer_categories = parsed_constraints.get(
            "prefer_categories",
            [],
        )
        prefer_colors = parsed_constraints.get("prefer_colors", [])
        preferred_style = STYLE_SHIFT_QUERY.get(
            parsed_constraints.get("style_shift")
        )
        query_parts = [
            *prefer_categories,
            *prefer_colors,
            *([preferred_style] if preferred_style else []),
        ]
        query = " ".join(query_parts) or message
        recalled = self.retrieval(query, limit)

        excluded_ids = {
            *map(str, conversation_state.get("excluded_item_ids", [])),
            *map(str, conversation_state.get("locked_item_ids", [])),
            *map(
                str,
                parsed_constraints.get("bound_exclude_item_ids", []),
            ),
            *map(
                str,
                parsed_constraints.get("bound_keep_item_ids", []),
            ),
        }
        excluded_categories = set(
            parsed_constraints.get("exclude_categories", [])
        )
        preferred_categories = set(prefer_categories)
        preferred_colors = set(prefer_colors)
        preferred_styles = {preferred_style} if preferred_style else set()
        candidates = []
        for recall_rank, item in enumerate(recalled):
            item_id = str(item["item_id"])
            if item_id in excluded_ids:
                continue
            resolved = self.resolver(item_id)
            if not resolved.get("found"):
                continue
            candidate = _candidate_fields(resolved)
            categories, colors, styles = _metadata_terms(candidate)
            if categories & excluded_categories:
                continue
            preference_score = (
                3 * len(categories & preferred_categories)
                + 2 * len(colors & preferred_colors)
                + len(styles & preferred_styles)
            )
            candidates.append(
                (preference_score, -recall_rank, candidate)
            )

        candidates.sort(
            key=lambda entry: (entry[0], entry[1]),
            reverse=True,
        )
        replacement_candidates = [entry[2] for entry in candidates]
        ranking_context = {
            entry[2]["item_id"]: {
                "preference_score": entry[0],
                "text_rank": -entry[1],
            }
            for entry in candidates
        }
        return {
            "replacement_candidates": replacement_candidates,
            "ranking_context": ranking_context,
            "message": (
                "已找到符合约束的替换候选。"
                if replacement_candidates
                else "暂未找到符合当前约束的替换候选。"
            ),
        }
