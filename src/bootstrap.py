"""幂等创建可再分发的三件合成商品演示数据。"""

import json
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

ITEMS = (
    ("demo-blue-shirt", "蓝色简约衬衫，适合通勤", "上衣", "衬衫", "蓝色", (65, 105, 225)),
    ("demo-black-pants", "黑色简约长裤，适合通勤", "下装", "长裤", "黑色", (30, 30, 30)),
    ("demo-white-shoes", "白色休闲鞋，适合通勤", "鞋", "休闲鞋", "白色", (235, 235, 235)),
)


def build_records(bucket):
    return [
        {
            "item_id": item_id,
            "bucket": bucket,
            "object_key": f"demo/items/{item_id}.jpg",
            "retrieval_text": text,
            "category": category,
            "sub_category": sub_category,
            "colors": [color],
            "style": ["简约"],
            "scene": ["通勤"],
            "confidence": 1.0,
        }
        for item_id, text, category, sub_category, color, _rgb in ITEMS
    ]


def bootstrap():
    from src.config import MINIO_BUCKET, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
    from src.data.minio_client import create_minio_client
    from src.embeddings.chinese_clip import ChineseCLIPEmbeddings
    from src.embeddings.dashscope_emb import DashScopeEmbeddings
    from src.vectordb.chinese_clip_image_store import upsert_image_embeddings
    from src.vectordb.polyvore_text_store import upsert_text_embeddings

    processed = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
    chroma = Path(os.getenv("CHROMA_PERSIST_DIR", "chroma_data"))
    ready = Path(os.getenv("SEED_READY_FILE", "data/.seed-ready"))
    processed.mkdir(parents=True, exist_ok=True)
    chroma.mkdir(parents=True, exist_ok=True)
    records = build_records(MINIO_BUCKET)

    minio = create_minio_client()
    if not minio.bucket_exists(MINIO_BUCKET):
        minio.make_bucket(MINIO_BUCKET)
    for record, (*_metadata, rgb) in zip(records, ITEMS):
        buffer = BytesIO()
        Image.new("RGB", (224, 224), rgb).save(buffer, "JPEG")
        data = buffer.getvalue()
        minio.put_object(
            MINIO_BUCKET,
            record["object_key"],
            BytesIO(data),
            len(data),
            content_type="image/jpeg",
        )

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            session.run("CREATE CONSTRAINT item_id IF NOT EXISTS FOR (n:Item) REQUIRE n.item_id IS UNIQUE")
            session.run("CREATE CONSTRAINT outfit_id IF NOT EXISTS FOR (n:Outfit) REQUIRE n.outfit_id IS UNIQUE")
            session.run(
                "MERGE (o:Outfit {outfit_id:'demo-outfit'}) "
                "WITH o UNWIND $ids AS id MERGE (i:Item {item_id:id}) MERGE (i)-[:IN_OUTFIT]->(o)",
                ids=[record["item_id"] for record in records],
            ).consume()
    finally:
        driver.close()

    lines = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    for name in (
        "polyvore_items_sample.jsonl",
        "polyvore_neo4j_items_manifest.jsonl",
        "polyvore_neo4j_items_retrieval.jsonl",
        "polyvore_items_enriched_sample.jsonl",
    ):
        (processed / name).write_text(lines, encoding="utf-8")
    image_embeddings = ChineseCLIPEmbeddings()
    text_embeddings = DashScopeEmbeddings()
    images = []
    for record in records:
        response = minio.get_object(MINIO_BUCKET, record["object_key"])
        try:
            images.append(response.read())
        finally:
            response.close()
            response.release_conn()
    upsert_image_embeddings(
        records,
        image_embeddings.embed_images(images),
        persist_dir=chroma,
    )
    upsert_text_embeddings(
        records,
        text_embeddings.embed_documents([record["retrieval_text"] for record in records]),
        persist_dir=chroma,
    )
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.write_text("synthetic-demo-v1\n", encoding="utf-8")


def main():
    bootstrap()
    print("合成演示数据已就绪")


if __name__ == "__main__":
    main()
