import importlib
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


COLLECTION_NAME = "products_text_v3_v1"
METADATA_FIELDS = {
    "item_id",
    "bucket",
    "object_key",
    "category",
    "sub_category",
    "colors",
    "style",
    "scene",
    "confidence",
}


def sample_items(count=6):
    """构造增强 JSONL 的最小可信记录。"""
    return [
        {
            "item_id": str(index),
            "bucket": "shopping-qna",
            "object_key": f"polyvore/items/{index}.jpg",
            "category": "上衣",
            "sub_category": "衬衫",
            "colors": ["蓝色", "白色"],
            "style": ["休闲"],
            "scene": ["日常穿搭"],
            "retrieval_text": f"第{index}件蓝白休闲衬衫",
            "confidence": 0.9,
        }
        for index in range(1, count + 1)
    ]


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


class PolyvoreTextStoreTest(unittest.TestCase):
    def test_五条增强记录转换并写入独立_collection(self):
        store = import_required("src.vectordb.polyvore_text_store")
        items = sample_items(5)
        vectors = [[float(index)] * 1024 for index in range(5)]
        collection = MagicMock()
        chroma_client = MagicMock()
        chroma_client.get_or_create_collection.return_value = collection

        records = store.build_polyvore_text_records(items)
        result = store.upsert_text_embeddings(
            items=items,
            embeddings=vectors,
            persist_dir=Path("不会实际写入"),
            chroma_client=chroma_client,
        )

        self.assertEqual(store.COLLECTION_NAME, COLLECTION_NAME)
        self.assertEqual(len(records), 5)
        self.assertEqual([record["id"] for record in records], ["1", "2", "3", "4", "5"])
        self.assertEqual(
            [record["document"] for record in records],
            [item["retrieval_text"] for item in items],
        )
        for record, item in zip(records, items):
            self.assertEqual(set(record["metadata"]), METADATA_FIELDS)
            self.assertIsInstance(record["id"], str)
            self.assertIsInstance(record["metadata"]["item_id"], str)
            self.assertEqual(json.loads(record["metadata"]["colors"]), item["colors"])
            self.assertEqual(json.loads(record["metadata"]["style"]), item["style"])
            self.assertEqual(json.loads(record["metadata"]["scene"]), item["scene"])

        chroma_client.get_or_create_collection.assert_called_once_with(
            name=COLLECTION_NAME
        )
        upsert = collection.upsert.call_args.kwargs
        self.assertEqual(upsert["ids"], [record["id"] for record in records])
        self.assertEqual(upsert["embeddings"], vectors)
        self.assertEqual(upsert["documents"], [record["document"] for record in records])
        self.assertEqual(upsert["metadatas"], [record["metadata"] for record in records])
        self.assertEqual(result, {"ingested": 5, "collection": COLLECTION_NAME})

    def test_拒绝非1024维文本向量(self):
        store = import_required("src.vectordb.polyvore_text_store")

        with self.assertRaisesRegex(ValueError, "1024"):
            store.upsert_text_embeddings(
                items=sample_items(1),
                embeddings=[[0.1] * 4],
                chroma_client=MagicMock(),
            )

    def test_cli_只读取前五条并使用注入的假_embedding_和_chroma(self):
        cli = import_required("src.cli_polyvore_text_index")
        items = sample_items(6)
        vectors = [[float(index)] * 1024 for index in range(5)]
        embedding_model = MagicMock()
        embedding_model.embed_documents.return_value = vectors
        chroma_client = MagicMock()
        fake_result = {"ingested": 5, "collection": COLLECTION_NAME}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enriched_path = temp_path / "enriched.jsonl"
            enriched_path.write_text(
                "".join(
                    json.dumps(item, ensure_ascii=False) + "\n" for item in items
                ),
                encoding="utf-8",
            )
            with patch.object(
                cli,
                "upsert_text_embeddings",
                return_value=fake_result,
            ) as upsert:
                result = cli.ingest_enriched_sample(
                    enriched_path=enriched_path,
                    persist_dir=temp_path / "chroma",
                    limit=5,
                    embedding_model=embedding_model,
                    chroma_client=chroma_client,
                )

        embedding_model.embed_documents.assert_called_once_with(
            [item["retrieval_text"] for item in items[:5]]
        )
        call_args = upsert.call_args.kwargs
        self.assertEqual(call_args["items"], items[:5])
        self.assertEqual(call_args["embeddings"], vectors)
        self.assertIs(call_args["chroma_client"], chroma_client)
        self.assertEqual(result, fake_result)

    def test_旧文本_collection_保持不变(self):
        project_root = Path(__file__).resolve().parents[1]
        source = (project_root / "src/vectordb/text_store.py").read_text(
            encoding="utf-8"
        )
        module = ast.parse(source)
        assignments = {
            target.id: ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        self.assertEqual(assignments["COLLECTION_NAME"], "products_text")


if __name__ == "__main__":
    unittest.main()
