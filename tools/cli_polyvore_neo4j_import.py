import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.data.polyvore_neo4j_import import (
    DEFAULT_ENRICHED_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_VALID_PATH,
    create_neo4j_driver,
    import_rows,
    prepare_import_rows,
    query_anchor_candidates,
)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="导入 Polyvore 最小 Neo4j outfit 图")
    parser.add_argument("--valid", type=Path, default=DEFAULT_VALID_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--enriched", type=Path, default=DEFAULT_ENRICHED_PATH)
    parser.add_argument("--target-outfits", type=int, default=40)
    parser.add_argument("--batch-id", default="polyvore-valid-v1-anchor40")
    parser.add_argument("--anchor-item-id", default="199614803")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        parser.error("必须通过 NEO4J_PASSWORD 环境变量提供密码")

    prepared = prepare_import_rows(
        valid_path=args.valid,
        manifest_path=args.manifest,
        enriched_path=args.enriched,
        target_outfits=args.target_outfits,
    )
    driver = create_neo4j_driver(uri, user, password)
    try:
        imported = import_rows(driver, prepared.pop("rows"), args.batch_id)
        candidates = query_anchor_candidates(
            driver,
            args.anchor_item_id,
            args.top_k,
        )
    finally:
        driver.close()

    print(
        json.dumps(
            {
                "slice": prepared,
                "database": imported,
                "anchor_item_id": args.anchor_item_id,
                "anchor_candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
