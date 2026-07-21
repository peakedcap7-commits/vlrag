import json
from pathlib import Path


STRING_FIELDS = (
    "bucket",
    "object_key",
    "retrieval_text",
    "category",
    "sub_category",
)
LIST_FIELDS = ("colors", "style", "scene")


def build_item_index(records=None, jsonl_path=None):
    """从内存记录或本地 JSONL 构建商品索引。"""
    items = list(records or [])
    if jsonl_path is not None:
        items.extend(
            json.loads(line)
            for line in Path(jsonl_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return {str(item["item_id"]): dict(item) for item in items}


def resolve_item(item_id, item_index, enriched_index=None):
    """合并样本与增强索引并返回严格字段的商品信息。"""
    item_id = str(item_id)
    base = item_index.get(item_id)
    enriched = (enriched_index or {}).get(item_id)
    found = base is not None or enriched is not None
    merged = dict(base or {})
    merged.update(enriched or {})

    result = {"found": found, "item_id": item_id}
    result.update({field: merged.get(field) or "" for field in STRING_FIELDS})
    result.update({field: merged.get(field) or [] for field in LIST_FIELDS})
    return result
