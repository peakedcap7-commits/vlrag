import argparse
import json
from pathlib import Path

from src.polyvore_recommend_service import (
    PolyvoreRecommendConfig,
    build_polyvore_recommend_service,
)


def _bounded_retrieval_limit(value):
    """限制每路检索数量为一到五。"""
    limit = int(value)
    if not 1 <= limit <= 5:
        raise argparse.ArgumentTypeError("retrieval-limit 必须在 1 到 5 之间")
    return limit


def _positive_integer(value):
    """解析正整数。"""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("top-k 必须大于零")
    return number


def main():
    parser = argparse.ArgumentParser(description="执行 Polyvore 检索与穿搭推荐")
    parser.add_argument("--query", required=True, help="中文商品查询")
    defaults = PolyvoreRecommendConfig()
    parser.add_argument("--valid", type=Path, default=defaults.valid_path)
    parser.add_argument("--persist-dir", type=Path, default=defaults.persist_dir)
    parser.add_argument("--sample", type=Path, default=defaults.sample_path)
    parser.add_argument("--enriched", type=Path, default=defaults.enriched_path)
    parser.add_argument("--retrieval-limit", type=_bounded_retrieval_limit, default=2)
    parser.add_argument("--top-k", type=_positive_integer, default=5)
    args = parser.parse_args()

    service = build_polyvore_recommend_service(
        PolyvoreRecommendConfig(
            persist_dir=args.persist_dir,
            valid_path=args.valid,
            sample_path=args.sample,
            enriched_path=args.enriched,
        )
    )
    try:
        result = service.recommend(
            query=args.query,
            top_k=args.top_k,
            retrieval_limit=args.retrieval_limit,
        )
    finally:
        service.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
