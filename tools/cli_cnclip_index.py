import argparse
import json
from pathlib import Path

from src.vectordb.chinese_clip_image_store import upsert_image_embeddings


DEFAULT_ENRICHED_PATH = Path("data/processed/polyvore_items_enriched_sample.jsonl")
DEFAULT_PERSIST_DIR = Path("chroma_data")


def ingest_enriched_sample(
    enriched_path=DEFAULT_ENRICHED_PATH,
    persist_dir=DEFAULT_PERSIST_DIR,
    limit=5,
    minio_client=None,
    embeddings=None,
    chroma_client=None,
):
    """编排最多五条 MinIO 图片的 Chinese-CLIP 向量写入。"""
    if not 1 <= limit <= 5:
        raise ValueError("limit 必须在 1 到 5 之间")
    items = [
        json.loads(line)
        for line in Path(enriched_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][:limit]

    if minio_client is None:
        from src.data.minio_client import create_minio_client

        minio_client = create_minio_client()
    if embeddings is None:
        from src.embeddings.chinese_clip import ChineseCLIPEmbeddings

        embeddings = ChineseCLIPEmbeddings()

    vectors = []
    for item in items:
        response = minio_client.get_object(item["bucket"], item["object_key"])
        try:
            vectors.append(embeddings.embed_image(response.read()))
        finally:
            response.close()
            response.release_conn()

    return upsert_image_embeddings(
        items=items,
        embeddings=vectors,
        persist_dir=persist_dir,
        chroma_client=chroma_client,
    )


def _parse_limit(value):
    """限制索引 smoke 只能处理一到五条。"""
    limit = int(value)
    if not 1 <= limit <= 5:
        raise argparse.ArgumentTypeError("limit 必须在 1 到 5 之间")
    return limit


def main():
    parser = argparse.ArgumentParser(description="写入 Chinese-CLIP 图片向量小样本")
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--persist-dir", type=Path, default=DEFAULT_PERSIST_DIR)
    parser.add_argument("--limit", type=_parse_limit, default=5)
    args = parser.parse_args()
    result = ingest_enriched_sample(
        enriched_path=args.enriched,
        persist_dir=args.persist_dir,
        limit=args.limit,
    )
    print(f"写入条数：{result['ingested']}，collection：{result['collection']}")


if __name__ == "__main__":
    main()
