import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, call


class PolyvorePreviewTest(unittest.TestCase):
    def test_为_manifest_中的每个商品生成预签名图片预览(self):
        from src.data.polyvore_preview import generate_preview

        records = [
            {
                "item_id": "175787103",
                "bucket": "shopping-qna",
                "object_key": "polyvore/items/175787103.jpg",
                "source_file": "175787103.jpg",
                "source_split": "nondisjoint/validation",
            },
            {
                "item_id": "175787104",
                "bucket": "shopping-qna",
                "object_key": "polyvore/items/175787104.jpg",
                "source_file": "175787104.jpg",
                "source_split": "nondisjoint/validation",
            },
        ]
        urls = [
            "http://localhost:9000/shopping-qna/175787103.jpg?signature=first",
            "http://localhost:9000/shopping-qna/175787104.jpg?signature=second",
        ]
        client = MagicMock()
        client.presigned_get_object.side_effect = urls

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = temp_path / "manifest.jsonl"
            output_path = temp_path / "preview.html"
            manifest_path.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )

            result = generate_preview(
                manifest_path=manifest_path,
                output_path=output_path,
                expires_hours=1,
                client=client,
            )
            html = output_path.read_text(encoding="utf-8")

        self.assertEqual(
            client.presigned_get_object.call_args_list,
            [
                call(
                    "shopping-qna",
                    "polyvore/items/175787103.jpg",
                    expires=timedelta(hours=1),
                ),
                call(
                    "shopping-qna",
                    "polyvore/items/175787104.jpg",
                    expires=timedelta(hours=1),
                ),
            ],
        )
        self.assertEqual(result["generated"], 2)
        for record, url in zip(records, urls):
            self.assertIn(record["item_id"], html)
            self.assertIn(record["object_key"], html)
            self.assertIn(url, html)


if __name__ == "__main__":
    unittest.main()
