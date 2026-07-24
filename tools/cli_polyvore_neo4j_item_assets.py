import argparse
import json
from pathlib import Path

from src.data.minio_client import create_minio_client
from src.data.polyvore_neo4j_import import prepare_import_rows
from src.data.polyvore_neo4j_manifest import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_PARQUET_PATH,
    import_item_assets,
    iter_validation_records,
)


def main():
    parser = argparse.ArgumentParser(description="补齐 Neo4j 切片商品图片和 manifest")
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()

    prepared = prepare_import_rows()
    target_item_ids = {row["item_id"] for row in prepared["rows"]}
    result = import_item_assets(
        records=iter_validation_records(args.parquet),
        target_item_ids=target_item_ids,
        manifest_path=args.manifest,
        client=create_minio_client(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
