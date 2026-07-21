import argparse
import json
import tempfile
from pathlib import Path

import pyarrow.parquet as pq

from src.data.minio_client import create_minio_client, upload_image


DEFAULT_PARQUET_PATH = Path(
    r"D:\datasets\polyvore-outfits\data\nondisjoint\validation.parquet"
)
DEFAULT_MANIFEST_PATH = Path(
    r"D:\pj\vlrag\shopping-qna\data\processed\polyvore_items_sample.jsonl"
)


def import_validation_sample(
    parquet_path=DEFAULT_PARQUET_PATH,
    manifest_path=DEFAULT_MANIFEST_PATH,
    limit=100,
    bucket="shopping-qna",
    client=None,
):
    """上传 Polyvore 验证集小样本并写入 JSONL 清单。"""
    if limit > 0:
        batches = pq.ParquetFile(parquet_path).iter_batches(batch_size=limit)
        batch = next(batches, None)
        records = batch.to_pylist() if batch else []
    else:
        records = []
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    client = client or create_minio_client()
    uploaded = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        with manifest_path.open("w", encoding="utf-8") as manifest_file:
            for record in records:
                item_id = str(record["item_id"])
                image = record["image"]
                image_path = Path(temp_dir) / f"{item_id}.jpg"
                image_path.write_bytes(image["bytes"])
                object_key = f"polyvore/items/{item_id}.jpg"

                upload_image(
                    image_path,
                    object_key=object_key,
                    bucket=bucket,
                    client=client,
                )
                manifest_file.write(
                    json.dumps(
                        {
                            "item_id": item_id,
                            "bucket": bucket,
                            "object_key": object_key,
                            "source_file": image["path"],
                            "source_split": "nondisjoint/validation",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                uploaded += 1

    return {"uploaded": uploaded, "manifest_lines": uploaded}


def main():
    parser = argparse.ArgumentParser(description="导入 Polyvore 验证集图片小样本")
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--bucket", default="shopping-qna")
    args = parser.parse_args()

    result = import_validation_sample(
        parquet_path=args.parquet,
        manifest_path=args.manifest,
        limit=args.limit,
        bucket=args.bucket,
    )
    print(
        f"上传成功数量：{result['uploaded']}，"
        f"manifest 行数：{result['manifest_lines']}"
    )


if __name__ == "__main__":
    main()
