import csv
import json
import re
from io import BytesIO
from pathlib import Path


DEFAULT_PARQUET_PATH = Path(
    r"D:\datasets\polyvore-outfits\data\nondisjoint\validation.parquet"
)
DEFAULT_MANIFEST_PATH = Path(
    "data/processed/polyvore_neo4j_items_manifest.jsonl"
)
DEFAULT_RETRIEVAL_MANIFEST_PATH = Path(
    "data/processed/polyvore_neo4j_items_retrieval.jsonl"
)
DEFAULT_ITEM_METADATA_PATH = Path(
    r"D:\datasets\polyvore-outfits\polyvore_item_metadata.json"
)
DEFAULT_CATEGORIES_PATH = Path(r"D:\datasets\polyvore-outfits\categories.csv")
DEFAULT_BUCKET = "shopping-qna"

SEMANTIC_CATEGORY_CN = {
    "all-body": "连体服装",
    "bottoms": "下装",
    "bags": "包袋",
    "jewellery": "首饰",
    "tops": "上衣",
    "shoes": "鞋履",
    "outerwear": "外套",
    "scarves": "围巾",
    "hats": "帽子",
    "sunglasses": "太阳镜",
    "accessories": "配饰",
}

CATEGORY_CN = {
    "dress": "连衣裙",
    "shorts": "短裤",
    "bag": "包",
    "necklace": "项链",
    "top": "上衣",
    "earrings": "耳环",
    "turtleneck sweater": "高领毛衣",
    "bracelet": "手链",
    "heels": "高跟鞋",
    "blazer": "西装外套",
    "jeans": "牛仔裤",
    "sandals": "凉鞋",
    "tote": "托特包",
    "trench coat": "风衣",
    "purse": "手提包",
    "clutch": "手拿包",
    "scarf": "围巾",
    "tshirt": "T恤",
    "tank": "背心",
    "pant": "裤子",
    "pants": "裤子",
    "blouse": "衬衫",
    "ring": "戒指",
    "winter hat": "冬帽",
    "sunglasses": "太阳镜",
    "smartphone cases/tech items": "数码配件",
    "backpack": "双肩包",
    "flats": "平底鞋",
    "platform shoes": "厚底鞋",
    "swimsuit": "泳装",
    "romper": "连体裤",
    "brooch": "胸针",
    "male scarves": "围巾",
    "booties": "短靴",
    "belt": "腰带",
    "parka": "派克外套",
    "skirt": "半身裙",
    "male sneakers": "运动鞋",
    "gown": "礼服",
    "headband": "发带",
    "watch": "手表",
    "jacket/coat": "夹克外套",
    "sweater": "毛衣",
    "gloves": "手套",
}

COLOR_CN = {
    "blue": "蓝色",
    "navy": "深蓝色",
    "black": "黑色",
    "white": "白色",
    "red": "红色",
    "green": "绿色",
    "grey": "灰色",
    "gray": "灰色",
    "pink": "粉色",
    "yellow": "黄色",
    "brown": "棕色",
    "beige": "米色",
    "purple": "紫色",
    "orange": "橙色",
    "gold": "金色",
    "silver": "银色",
}


def iter_validation_records(parquet_path=DEFAULT_PARQUET_PATH, batch_size=256):
    """分批读取 validation Parquet，避免一次加载全部图片。"""
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(parquet_path)
    for batch in parquet_file.iter_batches(
        batch_size=batch_size,
        columns=["item_id", "image"],
    ):
        yield from batch.to_pylist()


def _object_exists(client, bucket, object_key):
    try:
        client.stat_object(bucket, object_key)
        return True
    except Exception as exc:
        if getattr(exc, "code", "") in {"NoSuchKey", "NoSuchObject", "NotFound"}:
            return False
        raise


def import_item_assets(
    records,
    target_item_ids,
    manifest_path=DEFAULT_MANIFEST_PATH,
    bucket=DEFAULT_BUCKET,
    client=None,
):
    """幂等补齐目标图片，并生成完整基础 manifest。"""
    if client is None:
        from src.data.minio_client import create_minio_client

        client = create_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    remaining = {str(item_id) for item_id in target_item_ids}
    manifest_records = []
    uploaded = 0
    skipped = 0
    for record in records:
        item_id = str(record.get("item_id", "")).strip()
        if item_id not in remaining:
            continue
        image = record.get("image") or {}
        image_bytes = image.get("bytes")
        if not image_bytes:
            raise ValueError(f"item {item_id} 缺少图片字节")
        object_key = f"polyvore/items/{item_id}.jpg"
        if _object_exists(client, bucket, object_key):
            skipped += 1
        else:
            client.put_object(
                bucket,
                object_key,
                BytesIO(image_bytes),
                len(image_bytes),
                content_type="image/jpeg",
            )
            uploaded += 1
        manifest_records.append(
            {
                "item_id": item_id,
                "bucket": bucket,
                "object_key": object_key,
                "source_file": image.get("path") or "",
                "source_split": "nondisjoint/validation",
            }
        )
        remaining.remove(item_id)
        if not remaining:
            break

    if remaining:
        raise ValueError(f"Parquet 缺少图片 item：{sorted(remaining)}")

    manifest_records.sort(key=lambda item: item["item_id"])
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in manifest_records
        ),
        encoding="utf-8",
    )
    temporary_path.replace(manifest_path)
    return {
        "target_items": len(target_item_ids),
        "uploaded": uploaded,
        "skipped": skipped,
        "manifest_lines": len(manifest_records),
    }


def load_category_map(categories_path=DEFAULT_CATEGORIES_PATH):
    """读取 Polyvore 类别映射，保留原始英文类别事实。"""
    with Path(categories_path).open(encoding="utf-8", newline="") as source:
        return {
            str(row[0]): (row[1], row[2])
            for row in csv.reader(source)
            if len(row) >= 3
        }


def _extract_colors(metadata):
    """仅从已有文本标签抽取显式颜色词，不推断材质或功能属性。"""
    related = metadata.get("related") or []
    source = " ".join(
        [str(metadata.get("url_name", "")), *(str(value) for value in related)]
    ).lower()
    tokens = set(re.findall(r"[a-z]+", source))
    return list(dict.fromkeys(COLOR_CN[token] for token in COLOR_CN if token in tokens))


def build_retrieval_records(manifest_records, item_metadata, category_map):
    """将图片清单与基础 metadata 合并成无 VLM 的中文检索记录。"""
    records = []
    for manifest in manifest_records:
        item_id = str(manifest["item_id"])
        metadata = item_metadata.get(item_id, {})
        category_id = str(metadata.get("category_id", ""))
        category_name, mapped_semantic = category_map.get(
            category_id,
            ("", metadata.get("semantic_category", "")),
        )
        semantic_category = metadata.get("semantic_category") or mapped_semantic
        category = SEMANTIC_CATEGORY_CN.get(semantic_category, "服饰商品")
        sub_category = CATEGORY_CN.get(category_name, category)
        colors = _extract_colors(metadata)
        parts = [f"Polyvore 商品，类别：{sub_category}，大类：{category}"]
        if colors:
            parts.append(f"颜色：{'、'.join(colors)}")
        retrieval_text = "；".join(parts) + "。"
        records.append(
            {
                **manifest,
                "item_id": item_id,
                "url_name": metadata.get("url_name", ""),
                "semantic_category": semantic_category,
                "category_name": category_name,
                "category": category,
                "sub_category": sub_category,
                "colors": colors,
                "style": [],
                "details": [],
                "scene": [],
                "confidence": 0.0,
                "retrieval_text": retrieval_text,
            }
        )
    return records


def write_retrieval_manifest(
    records,
    output_path=DEFAULT_RETRIEVAL_MANIFEST_PATH,
):
    """原子写入检索清单，避免中途失败留下半文件。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    records = list(records)
    temporary_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return len(records)


def build_retrieval_manifest(
    manifest_path=DEFAULT_MANIFEST_PATH,
    item_metadata_path=DEFAULT_ITEM_METADATA_PATH,
    categories_path=DEFAULT_CATEGORIES_PATH,
    output_path=DEFAULT_RETRIEVAL_MANIFEST_PATH,
):
    """从现有 232 条图片清单生成基础中文检索清单。"""
    manifest_records = [
        json.loads(line)
        for line in Path(manifest_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    item_metadata = json.loads(
        Path(item_metadata_path).read_text(encoding="utf-8")
    )
    records = build_retrieval_records(
        manifest_records=manifest_records,
        item_metadata=item_metadata,
        category_map=load_category_map(categories_path),
    )
    write_retrieval_manifest(records, output_path)
    return records
