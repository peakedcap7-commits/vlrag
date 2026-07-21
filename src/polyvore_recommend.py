ANCHOR_FIELDS = (
    "item_id",
    "object_key",
    "retrieval_text",
    "sources",
    "rrf_score",
    "rule_score",
    "adjusted_score",
)


def recommend_polyvore_query(
    query,
    retrieval,
    outfit_query,
    item_to_outfit_ids,
    outfit_to_item_ids,
    top_k=None,
    resolver=None,
):
    """用检索 Top1 作为锚点扩展 outfit 候选。"""
    if top_k is not None and (
        isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1
    ):
        raise ValueError("top_k 必须是正整数")

    retrieval_results = retrieval(query)
    if not retrieval_results:
        return {"query": query, "anchor": None, "outfit_candidates": []}

    anchor_source = retrieval_results[0]
    anchor = {field: anchor_source.get(field) for field in ANCHOR_FIELDS}
    anchor_item_id = str(anchor["item_id"])
    outfit_results = outfit_query(
        anchor_item_id,
        item_to_outfit_ids,
        outfit_to_item_ids,
    )
    candidates = [
        {
            "candidate_item_id": str(item["candidate_item_id"]),
            "shared_outfit_ids": item["shared_outfit_ids"],
            "cooccurrence_count": item["cooccurrence_count"],
        }
        for item in outfit_results
        if str(item.get("candidate_item_id", "")) != anchor_item_id
    ]
    if top_k is not None:
        candidates = candidates[:top_k]
    if resolver is not None:
        anchor["resolved"] = resolver(anchor_item_id)
        for candidate in candidates:
            candidate["resolved"] = resolver(candidate["candidate_item_id"])
    return {
        "query": query,
        "anchor": anchor,
        "outfit_candidates": candidates,
    }
