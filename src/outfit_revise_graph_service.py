from src.outfit_revise_service import (
    normalize_categories,
    normalize_colors,
    normalize_styles,
)

STYLE_SHIFT_QUERY = {
    "more_formal": "正式",
    "more_casual": "休闲",
}

MATCH_REASONS = {
    "strong": "更适合作为当前搭配的替换单品。",
    "medium": "符合你的替换方向，整体风格较接近。",
    "weak": "符合基础条件，但当前数据中缺少明确搭配证据。",
}


def _unique_item_ids(values):
    return list(dict.fromkeys(str(value) for value in values if value))


def _retained_item_ids(conversation_state, parsed_constraints):
    state = conversation_state or {}
    parsed = parsed_constraints or {}
    return _unique_item_ids(
        [
            *state.get("locked_item_ids", []),
            *parsed.get("bound_keep_item_ids", []),
            state.get("anchor_item_id"),
        ]
    )


def _preference_score(candidate, parsed_constraints):
    categories = set(
        normalize_categories(
            f"{candidate.get('category', '')} "
            f"{candidate.get('sub_category', '')}"
        )
    )
    colors = set(normalize_colors(" ".join(candidate.get("colors", []))))
    styles = set(normalize_styles(" ".join(candidate.get("style", []))))
    preferred_categories = set(
        parsed_constraints.get("prefer_categories", [])
    )
    preferred_colors = set(parsed_constraints.get("prefer_colors", []))
    preferred_styles = set(
        parsed_constraints.get("normalized_constraints", {}).get(
            "prefer_styles",
            [],
        )
    )
    shifted_style = STYLE_SHIFT_QUERY.get(
        parsed_constraints.get("style_shift")
    )
    if shifted_style:
        preferred_styles.add(shifted_style)
    return (
        3 * len(categories & preferred_categories)
        + 2 * len(colors & preferred_colors)
        + len(styles & preferred_styles)
    )


class OutfitReviseGraphService:
    """只读验证替换候选的图共现，并生成用户态等级与排序。"""

    def __init__(self, outfit_provider):
        self.outfit_provider = outfit_provider

    def validate_and_rank(
        self,
        candidates,
        conversation_state,
        parsed_constraints,
        ranking_context=None,
    ):
        if parsed_constraints.get("needs_clarification"):
            return []
        if not candidates:
            return []

        candidate_ids = [str(item["item_id"]) for item in candidates]
        retained_ids = _retained_item_ids(
            conversation_state,
            parsed_constraints,
        )
        graph_rows = []
        if retained_ids:
            graph_rows = (
                self.outfit_provider.query_replacement_cooccurrences(
                    retained_ids,
                    candidate_ids,
                )
            )
        strong_ids = {
            str(row["candidate_item_id"])
            for row in graph_rows
            if int(row.get("cooccurrence_count", 0)) > 0
        }
        context = ranking_context or {}
        ranked = []
        for fallback_rank, candidate in enumerate(candidates):
            item = dict(candidate)
            item_id = str(item["item_id"])
            preference_score = _preference_score(
                item,
                parsed_constraints,
            )
            if item_id in strong_ids:
                match_level = "strong"
            elif preference_score > 0:
                match_level = "medium"
            else:
                match_level = "weak"
            item["match_level"] = match_level
            item["reason"] = MATCH_REASONS[match_level]
            text_rank = context.get(item_id, {}).get(
                "text_rank",
                fallback_rank,
            )
            ranked.append(
                (
                    item_id in strong_ids,
                    preference_score,
                    -int(text_rank),
                    item,
                )
            )

        ranked.sort(key=lambda entry: entry[:3], reverse=True)
        return [entry[3] for entry in ranked]
