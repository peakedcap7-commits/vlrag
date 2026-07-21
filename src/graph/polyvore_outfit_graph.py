def build_outfit_indexes(outfits):
    """构建商品到穿搭、穿搭到商品的稳定双向索引。"""
    outfit_items = {}
    for outfit in outfits:
        set_id = str(outfit.get("set_id", "")).strip()
        if not set_id:
            continue
        item_ids = {
            str(item.get("item_id", "")).strip()
            for item in outfit.get("items", [])
            if str(item.get("item_id", "")).strip()
        }
        outfit_items.setdefault(set_id, set()).update(item_ids)

    outfit_to_item_ids = {
        set_id: sorted(item_ids)
        for set_id, item_ids in outfit_items.items()
    }
    item_outfits = {}
    for set_id, item_ids in outfit_to_item_ids.items():
        for item_id in item_ids:
            item_outfits.setdefault(item_id, set()).add(set_id)
    item_to_outfit_ids = {
        item_id: sorted(set_ids)
        for item_id, set_ids in item_outfits.items()
    }
    return item_to_outfit_ids, outfit_to_item_ids


def query_outfit_candidates(
    anchor_item_id,
    item_to_outfit_ids,
    outfit_to_item_ids,
):
    """按共同出现的穿搭数量查询候选商品。"""
    anchor_item_id = str(anchor_item_id).strip()
    shared_outfits = {}
    for set_id in item_to_outfit_ids.get(anchor_item_id, []):
        for candidate_item_id in outfit_to_item_ids.get(set_id, []):
            if candidate_item_id == anchor_item_id:
                continue
            shared_outfits.setdefault(candidate_item_id, set()).add(set_id)

    results = [
        {
            "anchor_item_id": anchor_item_id,
            "candidate_item_id": candidate_item_id,
            "shared_outfit_ids": sorted(set_ids),
            "cooccurrence_count": len(set_ids),
        }
        for candidate_item_id, set_ids in shared_outfits.items()
    ]
    return sorted(
        results,
        key=lambda item: (-item["cooccurrence_count"], item["candidate_item_id"]),
    )
