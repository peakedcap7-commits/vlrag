from pathlib import Path


COLLECTION_NAME = "products_image_cnclip_v1"


def upsert_image_embeddings(
    items,
    embeddings,
    persist_dir=Path("chroma_data"),
    chroma_client=None,
):
    """将显式图片向量写入独立 Chinese-CLIP collection。"""
    if chroma_client is None:
        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(persist_dir))
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)
    collection.upsert(
        ids=[item["item_id"] for item in items],
        embeddings=embeddings,
        documents=[item["retrieval_text"] for item in items],
        metadatas=[
            {
                "item_id": item["item_id"],
                "bucket": item["bucket"],
                "object_key": item["object_key"],
                "retrieval_text": item["retrieval_text"],
            }
            for item in items
        ],
    )
    return {"ingested": len(items), "collection": COLLECTION_NAME}
