import tempfile
import unittest
from pathlib import Path


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeMinioClient:
    def get_object(self, bucket, object_key):
        return FakeResponse(f"{bucket}/{object_key}".encode())


class FakeImageEmbeddings:
    def embed_images(self, images):
        return [[float(index)] * 512 for index, _image in enumerate(images)]


class FakeTextEmbeddings:
    def embed_documents(self, texts):
        return [[float(index)] * 1024 for index, _text in enumerate(texts)]


class PolyvoreNeo4jChromaIndexTest(unittest.TestCase):
    def test_基础元数据生成中文检索文本且不编造不可见属性(self):
        from src.data.polyvore_neo4j_manifest import build_retrieval_records

        records = build_retrieval_records(
            manifest_records=[
                {
                    "item_id": "1",
                    "bucket": "shopping-qna",
                    "object_key": "polyvore/items/1.jpg",
                }
            ],
            item_metadata={
                "1": {
                    "category_id": "28",
                    "semantic_category": "bottoms",
                    "url_name": "blue waterproof leather pants by sample brand",
                    "related": ["Blue pants"],
                }
            },
            category_map={"28": ("pants", "bottoms")},
        )

        self.assertEqual(records[0]["item_id"], "1")
        self.assertEqual(records[0]["category"], "下装")
        self.assertEqual(records[0]["sub_category"], "裤子")
        self.assertEqual(records[0]["colors"], ["蓝色"])
        self.assertIn("蓝色", records[0]["retrieval_text"])
        self.assertIn("裤子", records[0]["retrieval_text"])
        for forbidden in ("防水", "真皮", "品牌", "保暖", "防风"):
            self.assertNotIn(forbidden, records[0]["retrieval_text"])

    def test_双向量库按批次写入且_item_id_保持一致(self):
        from tools.cli_polyvore_neo4j_chroma_index import index_records

        items = [
            {
                "item_id": str(index),
                "bucket": "shopping-qna",
                "object_key": f"polyvore/items/{index}.jpg",
                "retrieval_text": f"商品 {index}",
                "category": "上衣",
                "sub_category": "上衣",
                "colors": [],
                "style": [],
                "scene": [],
            }
            for index in range(3)
        ]
        image_calls = []
        text_calls = []

        result = index_records(
            items=items,
            batch_size=2,
            minio_client=FakeMinioClient(),
            image_embeddings=FakeImageEmbeddings(),
            text_embeddings=FakeTextEmbeddings(),
            image_upserter=lambda **kwargs: image_calls.append(kwargs),
            text_upserter=lambda **kwargs: text_calls.append(kwargs),
        )

        self.assertEqual(result["image_ingested"], 3)
        self.assertEqual(result["text_ingested"], 3)
        self.assertEqual(len(image_calls), 2)
        self.assertEqual(len(text_calls), 2)
        self.assertEqual(
            [item["item_id"] for call in image_calls for item in call["items"]],
            [item["item_id"] for call in text_calls for item in call["items"]],
        )

    def test_检索清单可原子写入_jsonl(self):
        from src.data.polyvore_neo4j_manifest import write_retrieval_manifest

        records = [{"item_id": "1", "retrieval_text": "蓝色裤子"}]
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "retrieval.jsonl"
            count = write_retrieval_manifest(records, output_path)
            content = output_path.read_text(encoding="utf-8")

        self.assertEqual(count, 1)
        self.assertIn('"item_id": "1"', content)
        self.assertIn("蓝色裤子", content)


if __name__ == "__main__":
    unittest.main()
