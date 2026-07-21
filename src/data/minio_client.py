import argparse
import json
from pathlib import Path

from minio import Minio

from src.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)


def create_minio_client(
    endpoint=None,
    access_key=None,
    secret_key=None,
    secure=None,
):
    """创建 MinIO 客户端。"""
    return Minio(
        endpoint or MINIO_ENDPOINT,
        access_key=access_key or MINIO_ACCESS_KEY,
        secret_key=secret_key or MINIO_SECRET_KEY,
        secure=MINIO_SECURE if secure is None else secure,
    )


def upload_image(
    file_path,
    object_key="polyvore/items/test.jpg",
    bucket=None,
    client=None,
):
    """上传本地 JPEG 图片并返回对象位置。"""
    file_path = Path(file_path)
    bucket = bucket or MINIO_BUCKET
    client = client or create_minio_client()

    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.fput_object(
        bucket,
        object_key,
        str(file_path),
        content_type="image/jpeg",
    )
    return {"bucket": bucket, "object_key": object_key}


def main():
    parser = argparse.ArgumentParser(description="上传本地测试图片到 MinIO")
    parser.add_argument("file_path", help="本地图片路径")
    parser.add_argument(
        "object_key",
        nargs="?",
        default="polyvore/items/test.jpg",
        help="MinIO 对象键",
    )
    args = parser.parse_args()
    result = upload_image(args.file_path, args.object_key)
    print(f"上传成功：{json.dumps(result, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
