import argparse
import json
from pathlib import Path

from src.graph.polyvore_outfit_graph import (
    build_outfit_indexes,
    query_outfit_candidates,
)


def _positive_integer(value):
    """解析正整数参数。"""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("top-k 必须大于零")
    return number


def main():
    parser = argparse.ArgumentParser(description="查询 Polyvore 穿搭共现候选")
    parser.add_argument("--valid", type=Path, required=True, help="valid.json 路径")
    parser.add_argument("--item-id", required=True, help="锚点商品 ID")
    parser.add_argument("--top-k", type=_positive_integer, default=10)
    args = parser.parse_args()

    outfits = json.loads(args.valid.read_text(encoding="utf-8"))
    item_to_outfit_ids, outfit_to_item_ids = build_outfit_indexes(outfits)
    results = query_outfit_candidates(
        args.item_id,
        item_to_outfit_ids,
        outfit_to_item_ids,
    )[:args.top_k]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
