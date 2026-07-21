import argparse
import json
from pathlib import Path

from src.polyvore_retrieval import DEFAULT_ENRICHED_PATH, retrieve_polyvore_query


def _parse_limit(value):
    """限制每路检索最多返回五条。"""
    limit = int(value)
    if not 1 <= limit <= 5:
        raise argparse.ArgumentTypeError("limit 必须在 1 到 5 之间")
    return limit


def main():
    parser = argparse.ArgumentParser(description="执行 Polyvore 三路检索与 RRF 融合")
    parser.add_argument("--query", required=True, help="中文商品查询")
    parser.add_argument("--persist-dir", type=Path, default=Path("chroma_data"))
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--limit", type=_parse_limit, default=2)
    args = parser.parse_args()

    import chromadb

    from src.embeddings.chinese_clip import ChineseCLIPEmbeddings
    from src.embeddings.dashscope_emb import DashScopeEmbeddings

    results = retrieve_polyvore_query(
        query=args.query,
        chroma_client=chromadb.PersistentClient(path=str(args.persist_dir)),
        text_embeddings=DashScopeEmbeddings(),
        image_embeddings=ChineseCLIPEmbeddings(),
        limit=args.limit,
        enriched_path=args.enriched,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
