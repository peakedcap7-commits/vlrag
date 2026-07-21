import argparse
import html
import json
from datetime import timedelta
from pathlib import Path

from src.data.minio_client import create_minio_client


DEFAULT_MANIFEST_PATH = Path(
    r"D:\pj\vlrag\shopping-qna\data\processed\polyvore_items_sample.jsonl"
)
DEFAULT_OUTPUT_PATH = Path(
    r"D:\pj\vlrag\shopping-qna\data\processed\polyvore_items_preview.html"
)


def generate_preview(
    manifest_path=DEFAULT_MANIFEST_PATH,
    output_path=DEFAULT_OUTPUT_PATH,
    expires_hours=1,
    client=None,
):
    """为 manifest 中的商品生成 MinIO 图片预览页。"""
    manifest_path = Path(manifest_path)
    output_path = Path(output_path)
    client = client or create_minio_client()
    records = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    cards = []
    for record in records:
        url = client.presigned_get_object(
            record["bucket"],
            record["object_key"],
            expires=timedelta(hours=expires_hours),
        )
        item_id = html.escape(str(record["item_id"]))
        object_key = html.escape(str(record["object_key"]))
        image_url = html.escape(str(url), quote=True)
        cards.append(
            f'<article class="card"><img src="{image_url}" alt="商品 {item_id}">'
            f"<strong>{item_id}</strong><code>{object_key}</code></article>"
        )

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polyvore 商品预览</title>
<style>
body {{ margin: 24px; font-family: sans-serif; background: #f5f5f5; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }}
.card {{ display: grid; gap: 8px; padding: 12px; background: white; border-radius: 8px; }}
.card img {{ width: 100%; aspect-ratio: 1; object-fit: contain; }}
.card code {{ overflow-wrap: anywhere; }}
</style>
</head>
<body>
<h1>Polyvore 商品预览</h1>
<main class="grid">{''.join(cards)}</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return {"generated": len(records), "path": str(output_path)}


def main():
    parser = argparse.ArgumentParser(description="生成 Polyvore MinIO 图片预览页")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--expires-hours", type=int, default=1)
    args = parser.parse_args()

    result = generate_preview(
        manifest_path=args.manifest,
        output_path=args.output,
        expires_hours=args.expires_hours,
    )
    print(f"生成条数：{result['generated']}，文件路径：{result['path']}")


if __name__ == "__main__":
    main()
