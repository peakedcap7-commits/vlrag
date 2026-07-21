import json
from pathlib import Path


COLLECTION_NAME = "products_text_v3_v1"
EMBEDDING_DIM = 1024


def build_polyvore_text_records(items):
    """校验增强记录并转换为 Chroma 写入结构。"""
    records = []
    item_ids = set()
    for item in items:
        item_id = str(item.get("item_id", "")).strip()
        retrieval_text = item.get("retrieval_text", "")
        if not item_id:
            raise ValueError("item_id 不能为空")
        if item_id in item_ids:
            raise ValueError(f"item_id 不能重复：{item_id}")
        if not isinstance(retrieval_text, str) or not retrieval_text.strip():
            raise ValueError(f"retrieval_text 不能为空：{item_id}")
        item_ids.add(item_id)
        records.append(
            {
                "id": item_id,
                "document": retrieval_text,
                "metadata": {
                    "item_id": item_id,
                    "bucket": item.get("bucket", ""),
                    "object_key": item.get("object_key", ""),
                    "category": item.get("category", ""),
                    "sub_category": item.get("sub_category", ""),
                    "colors": json.dumps(
                        item.get("colors", []), ensure_ascii=False, separators=(",", ":")
                    ),
                    "style": json.dumps(
                        item.get("style", []), ensure_ascii=False, separators=(",", ":")
                    ),
                    "scene": json.dumps(
                        item.get("scene", []), ensure_ascii=False, separators=(",", ":")
                    ),
                    "confidence": item.get("confidence", 0.0),
                },
            }
        )
    return records


def upsert_text_embeddings(
    items,
    embeddings,
    persist_dir=Path("chroma_data"),
    chroma_client=None,
):
    """将显式文本向量写入独立 Polyvore collection。"""
    if len(items) != len(embeddings):
        raise ValueError("items 与 embeddings 条数必须一致")
    if any(len(embedding) != EMBEDDING_DIM for embedding in embeddings):
        raise ValueError(f"文本向量维度必须为 {EMBEDDING_DIM}")
    records = build_polyvore_text_records(items)
    if chroma_client is None:
        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(persist_dir))
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)
    collection.upsert(
        ids=[record["id"] for record in records],
        embeddings=embeddings,
        documents=[record["document"] for record in records],
        metadatas=[record["metadata"] for record in records],
    )
    return {"ingested": len(records), "collection": COLLECTION_NAME}
