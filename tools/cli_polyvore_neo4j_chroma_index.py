import argparse
import json
from pathlib import Path

from src.data.polyvore_neo4j_manifest import (
    DEFAULT_CATEGORIES_PATH,
    DEFAULT_ITEM_METADATA_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_RETRIEVAL_MANIFEST_PATH,
    build_retrieval_manifest,
)
from src.vectordb.chinese_clip_image_store import upsert_image_embeddings
from src.vectordb.polyvore_text_store import upsert_text_embeddings


DEFAULT_PERSIST_DIR = Path("chroma_data")


def _batches(items, batch_size):
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def _read_minio_images(client, items):
    images = []
    for item in items:
        response = client.get_object(item["bucket"], item["object_key"])
        try:
            images.append(response.read())
        finally:
            response.close()
            response.release_conn()
    return images


def index_records(
    items,
    batch_size=8,
    channel="both",
    persist_dir=DEFAULT_PERSIST_DIR,
    minio_client=None,
    image_embeddings=None,
    text_embeddings=None,
    chroma_client=None,
    image_upserter=upsert_image_embeddings,
    text_upserter=upsert_text_embeddings,
):
    """按相同批次幂等 upsert 图片、文本向量，保证 ID 对齐。"""
    if batch_size < 1:
        raise ValueError("batch_size 必须大于零")
    if channel not in {"both", "image", "text"}:
        raise ValueError("channel 必须为 both、image 或 text")
    index_images = channel in {"both", "image"}
    index_texts = channel in {"both", "text"}
    if index_images and minio_client is None:
        from src.data.minio_client import create_minio_client

        minio_client = create_minio_client()
    if index_images and image_embeddings is None:
        from src.embeddings.chinese_clip import ChineseCLIPEmbeddings

        image_embeddings = ChineseCLIPEmbeddings()
    if index_texts and text_embeddings is None:
        from src.embeddings.dashscope_emb import DashScopeEmbeddings

        text_embeddings = DashScopeEmbeddings()

    image_ingested = 0
    text_ingested = 0
    for batch in _batches(list(items), batch_size):
        if index_images:
            image_bytes = _read_minio_images(minio_client, batch)
            if hasattr(image_embeddings, "embed_images"):
                image_vectors = image_embeddings.embed_images(image_bytes)
            else:
                image_vectors = [
                    image_embeddings.embed_image(value) for value in image_bytes
                ]
            image_upserter(
                items=batch,
                embeddings=image_vectors,
                persist_dir=persist_dir,
                chroma_client=chroma_client,
            )
            image_ingested += len(batch)

        if index_texts:
            text_vectors = text_embeddings.embed_documents(
                [item["retrieval_text"] for item in batch]
            )
            text_upserter(
                items=batch,
                embeddings=text_vectors,
                persist_dir=persist_dir,
                chroma_client=chroma_client,
            )
            text_ingested += len(batch)

    return {
        "image_ingested": image_ingested,
        "text_ingested": text_ingested,
        "image_failed": 0,
        "text_failed": 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="将 Neo4j 图切片商品幂等写入 Chroma 双向量库"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--retrieval-manifest",
        type=Path,
        default=DEFAULT_RETRIEVAL_MANIFEST_PATH,
    )
    parser.add_argument(
        "--item-metadata",
        type=Path,
        default=DEFAULT_ITEM_METADATA_PATH,
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=DEFAULT_CATEGORIES_PATH,
    )
    parser.add_argument("--persist-dir", type=Path, default=DEFAULT_PERSIST_DIR)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--channel",
        choices=("both", "image", "text"),
        default="both",
        help="选择全部、仅图片或仅文本通道，便于失败后幂等续跑",
    )
    args = parser.parse_args()

    items = build_retrieval_manifest(
        manifest_path=args.manifest,
        item_metadata_path=args.item_metadata,
        categories_path=args.categories,
        output_path=args.retrieval_manifest,
    )
    result = index_records(
        items=items,
        batch_size=args.batch_size,
        channel=args.channel,
        persist_dir=args.persist_dir,
    )
    print(
        json.dumps(
            {
                **result,
                "retrieval_manifest": str(args.retrieval_manifest),
                "records": len(items),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
