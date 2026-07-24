import json
import tempfile
import unittest
from pathlib import Path


class MissingObjectError(Exception):
    code = "NoSuchKey"


class FakeMinioClient:
    def __init__(self, existing=None):
        self.objects = set(existing or [])
        self.uploaded = []

    def bucket_exists(self, bucket):
        return True

    def stat_object(self, bucket, object_key):
        if (bucket, object_key) not in self.objects:
            raise MissingObjectError()
        return object()

    def put_object(self, bucket, object_key, data, length, content_type):
        self.objects.add((bucket, object_key))
        self.uploaded.append((bucket, object_key, data.read(), length, content_type))


class PolyvoreNeo4jManifestTest(unittest.TestCase):
    def test_缺失图片上传_已存在跳过_并写完整_manifest(self):
        from src.data.polyvore_neo4j_manifest import import_item_assets

        records = [
            {"item_id": "1", "image": {"bytes": b"one", "path": "1.jpg"}},
            {"item_id": "2", "image": {"bytes": b"two", "path": "2.jpg"}},
            {"item_id": "3", "image": {"bytes": b"three", "path": "3.jpg"}},
        ]
        client = FakeMinioClient(
            existing={("shopping-qna", "polyvore/items/1.jpg")}
        )

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.jsonl"
            result = import_item_assets(
                records=records,
                target_item_ids={"1", "2"},
                manifest_path=manifest_path,
                client=client,
            )
            lines = [
                json.loads(line)
                for line in manifest_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["manifest_lines"], 2)
        self.assertEqual([item["item_id"] for item in lines], ["1", "2"])
        self.assertEqual(lines[1]["object_key"], "polyvore/items/2.jpg")
        self.assertEqual(lines[1]["source_split"], "nondisjoint/validation")

    def test_目标_item_在_parquet缺失时失败(self):
        from src.data.polyvore_neo4j_manifest import import_item_assets

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "缺少图片"):
                import_item_assets(
                    records=[],
                    target_item_ids={"missing"},
                    manifest_path=Path(directory) / "manifest.jsonl",
                    client=FakeMinioClient(),
                )


if __name__ == "__main__":
    unittest.main()
