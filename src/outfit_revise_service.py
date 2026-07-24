import re


CATEGORY_ALIASES = {
    "裙子": ("连衣裙", "半身裙", "裙装", "短裙", "长裙", "裙子"),
    "裤子": ("牛仔裤", "西装裤", "长裤", "短裤", "裤装", "裤子"),
    "上衣": ("衬衫", "T恤", "吊带", "背心", "上装", "上衣"),
    "外套": ("西装外套", "夹克", "开衫", "大衣", "外套"),
    "鞋": ("运动鞋", "高跟鞋", "靴子", "鞋子", "鞋"),
}
COLOR_ALIASES = {
    "黑色": ("黑色", "黑"),
    "白色": ("白色", "白"),
    "蓝色": ("蓝色", "蓝"),
    "红色": ("红色", "红"),
    "粉色": ("粉色", "粉"),
    "绿色": ("绿色", "绿"),
    "米色": ("米色",),
    "灰色": ("灰色", "灰"),
    "棕色": ("棕色", "棕"),
    "紫色": ("紫色", "紫"),
    "黄色": ("黄色", "黄"),
}
STYLE_ALIASES = {
    "正式": ("正式", "商务"),
    "休闲": ("休闲", "日常"),
    "甜美": ("甜美", "可爱"),
    "酷感": ("酷感", "酷帅"),
    "复古": ("复古",),
}
EXCLUDE_KEYWORDS = ("不要", "去掉", "排除")
PREFER_KEYWORDS = ("换成", "改成", "替换为", "替换成", "替换", "想要")
KEEP_KEYWORDS = ("保留", "留下")
FULL_REWRITE_KEYWORDS = ("重新搭一套", "重搭一套", "全部替换", "整套重搭")
REFERENCE_WORDS = ("这个", "它", "这件", "这条")
REFERENCE_EXCLUDE_WORDS = ("换掉", "替换掉", "不要", "去掉", "排除")


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _extract_segments(message, keywords):
    segments = []
    for keyword in keywords:
        pattern = rf"{re.escape(keyword)}([^，。；,;]*)"
        segments.extend(re.findall(pattern, message))
    return segments


def _normalize_terms(text, aliases):
    matches = []
    for canonical, words in aliases.items():
        positions = [
            text.find(word)
            for word in words
            if text.find(word) >= 0
        ]
        if positions:
            matches.append((min(positions), canonical))
    return _unique(canonical for _, canonical in sorted(matches))


def normalize_categories(text):
    """把类目同义词归一为稳定主类目。"""
    return _normalize_terms(str(text or ""), CATEGORY_ALIASES)


def normalize_colors(text):
    """把常见颜色表达归一为稳定颜色名。"""
    return _normalize_terms(str(text or ""), COLOR_ALIASES)


def normalize_styles(text):
    """把常见风格表达归一为稳定风格名。"""
    return _normalize_terms(str(text or ""), STYLE_ALIASES)


def _extract_normalized(message, keywords, aliases):
    segments = _extract_segments(message, keywords)
    return _normalize_terms("，".join(segments), aliases)


def _item_categories(item):
    text = f"{item.get('category', '')} {item.get('sub_category', '')}"
    return normalize_categories(text)


def _matching_item_ids(state, category):
    return [
        str(item["item_id"])
        for item in state.get("item_metadata", [])
        if category in _item_categories(item)
    ]


def _resolve_reference_item_ids(state):
    selected_ids = state.get("selected_item_ids", [])
    if len(selected_ids) == 1:
        return list(selected_ids)
    anchor_item_id = state.get("anchor_item_id")
    if not selected_ids and anchor_item_id:
        return [anchor_item_id]
    return []


class OutfitReviseService:
    """仅解析和绑定改搭约束，不执行检索、替换或数据写入。"""

    def parse(self, message, conversation_state):
        message = (message or "").strip()
        state = conversation_state or {}
        exclude_categories = _extract_normalized(
            message,
            EXCLUDE_KEYWORDS,
            CATEGORY_ALIASES,
        )
        prefer_categories = _extract_normalized(
            message,
            PREFER_KEYWORDS,
            CATEGORY_ALIASES,
        )
        keep_categories = _extract_normalized(
            message,
            KEEP_KEYWORDS,
            CATEGORY_ALIASES,
        )
        prefer_colors = _extract_normalized(
            message,
            PREFER_KEYWORDS,
            COLOR_ALIASES,
        )
        prefer_styles = _normalize_terms(message, STYLE_ALIASES)
        rewrite_scope = (
            "full"
            if any(word in message for word in FULL_REWRITE_KEYWORDS)
            else "partial"
        )

        bound_keep_ids = []
        bound_exclude_ids = list(state.get("excluded_item_ids", []))
        questions = []
        has_reference = any(word in message for word in REFERENCE_WORDS)
        reference_ids = _resolve_reference_item_ids(state)

        if any(word in message for word in KEEP_KEYWORDS):
            if has_reference:
                if reference_ids:
                    bound_keep_ids.extend(reference_ids)
                else:
                    questions.append("请先选择你想保留的商品。")
            if keep_categories and not reference_ids:
                for category in keep_categories:
                    matches = _matching_item_ids(state, category)
                    if len(matches) == 1:
                        bound_keep_ids.extend(matches)
                    elif len(matches) > 1:
                        questions.append(f"你想保留哪一件{category}？")
                    else:
                        questions.append(
                            f"当前搭配里没有识别到{category}，"
                            "请确认要保留哪件商品。"
                        )
        bound_keep_ids.extend(state.get("locked_item_ids", []))

        has_reference_exclude = has_reference and any(
            word in message for word in REFERENCE_EXCLUDE_WORDS
        )
        if has_reference_exclude:
            if reference_ids:
                bound_exclude_ids.extend(reference_ids)
            else:
                questions.append("请先选择要替换的商品，或说明它的类别。")

        for category in exclude_categories:
            bound_exclude_ids.extend(_matching_item_ids(state, category))

        bound_keep_ids = _unique(bound_keep_ids)
        bound_exclude_ids = _unique(bound_exclude_ids)
        has_conflict = bool(
            set(bound_keep_ids) & set(bound_exclude_ids)
            or set(keep_categories) & set(exclude_categories)
        )
        if has_conflict:
            questions = [
                "“保留”与“不要”约束存在冲突，"
                "请确认要保留还是移除该商品。"
            ]

        style_shift = None
        if "更正式" in message or "正式一点" in message:
            style_shift = "more_formal"
        elif "更休闲" in message or "休闲一点" in message:
            style_shift = "more_casual"

        normalized_constraints = {
            "exclude_categories": exclude_categories,
            "prefer_categories": prefer_categories,
            "keep_categories": keep_categories,
            "prefer_colors": prefer_colors,
            "prefer_styles": prefer_styles,
            "rewrite_scope": rewrite_scope,
        }
        needs_clarification = bool(questions)
        has_binding = bool(bound_keep_ids or bound_exclude_ids)
        confidence = (
            0.3
            if needs_clarification
            else 0.95
            if has_binding
            else 0.85
        )
        return {
            "exclude_categories": exclude_categories,
            "prefer_categories": prefer_categories,
            "keep_items": bound_keep_ids,
            "prefer_colors": prefer_colors,
            "style_shift": style_shift,
            "rewrite_scope": rewrite_scope,
            "normalized_constraints": normalized_constraints,
            "bound_keep_item_ids": bound_keep_ids,
            "bound_exclude_item_ids": bound_exclude_ids,
            "needs_clarification": needs_clarification,
            "clarification_question": questions[0] if questions else "",
            "confidence": confidence,
        }
