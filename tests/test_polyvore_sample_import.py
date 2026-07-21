import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
from PIL import Image


def create_minimal_jpeg():
    """生成不依赖真实数据集的最小 JPEG。"""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


class PolyvoreSampleImportTest(unittest.TestCase):
    def test_按_limit_上传并写入五字段_manifest(self):
        from src.data.polyvore_import import import_validation_sample

        image_bytes = create_minimal_jpeg()
        records = [
            {
                "item_id": "175787103",
                "image": {"bytes": image_bytes, "path": "175787103.jpg"},
            },
            {
                "item_id": "175787104",
                "image": {"bytes": image_bytes, "path": "175787104.jpg"},
            },
            {
                "item_id": "175787105",
                "image": {"bytes": image_bytes, "path": "175787105.jpg"},
            },
        ]
        client = MagicMock()
        client.bucket_exists.return_value = True

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            parquet_path = temp_path / "validation.parquet"
            manifest_path = temp_path / "manifest.jsonl"
            pd.DataFrame(records).to_parquet(parquet_path, index=False)

            import_validation_sample(
                parquet_path=parquet_path,
                manifest_path=manifest_path,
                limit=2,
                bucket="shopping-qna",
                client=client,
            )

            manifest = [
                json.loads(line)
                for line in manifest_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(client.fput_object.call_count, 2)
        uploaded_locations = [
            call.args[:2] for call in client.fput_object.call_args_list
        ]
        self.assertEqual(
            uploaded_locations,
            [
                ("shopping-qna", "polyvore/items/175787103.jpg"),
                ("shopping-qna", "polyvore/items/175787104.jpg"),
            ],
        )
        self.assertEqual(
            manifest,
            [
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
            ],
        )
        self.assertTrue(all(len(row) == 5 for row in manifest))


if __name__ == "__main__":
    unittest.main()
