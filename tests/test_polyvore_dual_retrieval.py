import importlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path


TEXT_COLLECTION_NAME = "products_text_v3_v1"
IMAGE_COLLECTION_NAME = "products_image_cnclip_v1"


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


class FakeEmbeddings:
    """记录中文查询并返回固定向量，不加载真实模型。"""

    def __init__(self, vector):
        self.vector = vector
        self.queries = []

    def embed_query(self, query):
        self.queries.append(query)
        return self.vector


class FakeCollection:
    """返回 Chroma 原始查询结构，不连接本地数据库。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeChromaClient:
    """只允许读取本任务指定的两个 collection。"""

    def __init__(self, collections):
        self.collections = collections
        self.requested_names = []

    def get_collection(self, name):
        self.requested_names.append(name)
        return self.collections[name]


class PolyvoreDualRetrievalTest(unittest.TestCase):
    def test_bm25_从增强记录命中并参与_rrf(self):
        module = import_required("src.polyvore_retrieval")
        records = [
            {
                "item_id": "shirt",
                "object_key": "polyvore/items/shirt.jpg",
                "retrieval_text": "蓝色露肩休闲衬衫",
                "category": "上装",
                "colors": ["蓝色"],
            },
            {
                "item_id": "bracelet",
                "object_key": "polyvore/items/bracelet.jpg",
                "retrieval_text": "金色圆环手链",
                "category": "配饰",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enriched.jsonl"
            path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
                encoding="utf-8",
            )
            bm25_results = module.retrieve_bm25_results(
                "蓝色露肩休闲衬衫",
                path,
                limit=2,
            )

        results = module.fuse_ranked_results([], [], bm25_results=bm25_results)

        self.assertEqual(bm25_results[0]["item_id"], "shirt")
        self.assertEqual(results[0]["bm25_rank"], 1)
        self.assertEqual(results[0]["sources"], ["bm25"])
        self.assertAlmostEqual(results[0]["rrf_score"], 1 / 61)

    def test_rrf_按_item_id_合并双路并保留单路结果(self):
        module = import_required("src.polyvore_retrieval")
        text_results = [
            {
                "item_id": "shared",
                "object_key": "polyvore/items/shared.jpg",
                "retrieval_text": "蓝色休闲连衣裙",
            },
            {
                "item_id": "text-only",
                "object_key": "polyvore/items/text-only.jpg",
                "retrieval_text": "白色通勤衬衫",
            },
        ]
        image_results = [
            {
                "item_id": "image-only",
                "object_key": "polyvore/items/image-only.jpg",
                "retrieval_text": "蓝色运动外套",
            },
            {
                "item_id": "shared",
                "object_key": "polyvore/items/shared.jpg",
                "retrieval_text": "蓝色休闲连衣裙",
            },
        ]

        results = module.fuse_ranked_results(text_results, image_results, rrf_k=60)

        self.assertEqual([item["item_id"] for item in results], [
            "shared",
            "image-only",
            "text-only",
        ])
        self.assertEqual(
            set(results[0]),
            {
                "item_id",
                "object_key",
                "retrieval_text",
                "text_rank",
                "image_rank",
                "bm25_rank",
                "rrf_score",
                "sources",
            },
        )
        by_id = {item["item_id"]: item for item in results}
        self.assertEqual(by_id["shared"]["text_rank"], 1)
        self.assertEqual(by_id["shared"]["image_rank"], 2)
        self.assertIsNone(by_id["shared"]["bm25_rank"])
        self.assertEqual(by_id["shared"]["sources"], ["text", "image"])
        self.assertAlmostEqual(
            by_id["shared"]["rrf_score"],
            1 / 61 + 1 / 62,
        )
        self.assertEqual(by_id["text-only"]["text_rank"], 2)
        self.assertIsNone(by_id["text-only"]["image_rank"])
        self.assertIsNone(by_id["text-only"]["bm25_rank"])
        self.assertEqual(by_id["text-only"]["sources"], ["text"])
        self.assertAlmostEqual(by_id["text-only"]["rrf_score"], 1 / 62)
        self.assertIsNone(by_id["image-only"]["text_rank"])
        self.assertEqual(by_id["image-only"]["image_rank"], 1)
        self.assertIsNone(by_id["image-only"]["bm25_rank"])
        self.assertEqual(by_id["image-only"]["sources"], ["image"])
        self.assertAlmostEqual(by_id["image-only"]["rrf_score"], 1 / 61)

    def test_rrf_三路重复项合并且_bm25_单路结果保留(self):
        module = import_required("src.polyvore_retrieval")
        self.assertIn(
            "bm25_results",
            inspect.signature(module.fuse_ranked_results).parameters,
        )
        text_results = [
            {
                "item_id": "shared",
                "object_key": "polyvore/items/shared.jpg",
                "retrieval_text": "蓝色休闲连衣裙",
            },
            {
                "item_id": "text-only",
                "object_key": "polyvore/items/text-only.jpg",
                "retrieval_text": "白色通勤衬衫",
            },
        ]
        image_results = [
            {
                "item_id": "image-only",
                "object_key": "polyvore/items/image-only.jpg",
                "retrieval_text": "蓝色运动外套",
            },
            {
                "item_id": "shared",
                "object_key": "polyvore/items/shared.jpg",
                "retrieval_text": "蓝色休闲连衣裙",
            },
        ]
        bm25_results = [
            {
                "item_id": "bm25-only",
                "object_key": "polyvore/items/bm25-only.jpg",
                "retrieval_text": "蓝色亚麻半身裙",
            },
            {
                "item_id": "shared",
                "object_key": "polyvore/items/shared.jpg",
                "retrieval_text": "蓝色休闲连衣裙",
            },
        ]

        results = module.fuse_ranked_results(
            text_results,
            image_results,
            bm25_results=bm25_results,
            rrf_k=60,
        )

        self.assertEqual(results[0]["item_id"], "shared")
        self.assertTrue(
            all(
                set(item)
                == {
                    "item_id",
                    "object_key",
                    "retrieval_text",
                    "text_rank",
                    "image_rank",
                    "bm25_rank",
                    "rrf_score",
                    "sources",
                }
                for item in results
            )
        )
        by_id = {item["item_id"]: item for item in results}
        self.assertEqual(by_id["shared"]["text_rank"], 1)
        self.assertEqual(by_id["shared"]["image_rank"], 2)
        self.assertEqual(by_id["shared"]["bm25_rank"], 2)
        self.assertEqual(by_id["shared"]["sources"], ["text", "image", "bm25"])
        self.assertAlmostEqual(
            by_id["shared"]["rrf_score"],
            1 / 61 + 1 / 62 + 1 / 62,
        )
        self.assertIsNone(by_id["bm25-only"]["text_rank"])
        self.assertIsNone(by_id["bm25-only"]["image_rank"])
        self.assertEqual(by_id["bm25-only"]["bm25_rank"], 1)
        self.assertEqual(by_id["bm25-only"]["sources"], ["bm25"])
        self.assertAlmostEqual(by_id["bm25-only"]["rrf_score"], 1 / 61)

    def test_元数据规则命中排除_material_并按调整分排序(self):
        module = import_required("src.polyvore_retrieval")
        self.assertTrue(hasattr(module, "apply_metadata_rule_weights"))
        fused_results = [
            {
                "item_id": "all-fields",
                "object_key": "polyvore/items/all-fields.jpg",
                "retrieval_text": "蓝色休闲衬衫",
                "text_rank": 1,
                "image_rank": None,
                "bm25_rank": 1,
                "rrf_score": 0.03,
                "sources": ["text", "bm25"],
            },
            {
                "item_id": "material-only",
                "object_key": "polyvore/items/material-only.jpg",
                "retrieval_text": "基础款上衣",
                "text_rank": 2,
                "image_rank": None,
                "bm25_rank": None,
                "rrf_score": 0.02,
                "sources": ["text"],
            },
            {
                "item_id": "no-match",
                "object_key": "polyvore/items/no-match.jpg",
                "retrieval_text": "基础款长裤",
                "text_rank": None,
                "image_rank": 1,
                "bm25_rank": None,
                "rrf_score": 0.01,
                "sources": ["image"],
            },
        ]
        metadata_items = [
            {
                "item_id": "all-fields",
                "colors": ["蓝色"],
                "category": "上装",
                "sub_category": "衬衫",
                "style": ["休闲"],
                "details": ["露肩"],
                "scene": ["通勤"],
                "material": ["棉"],
            },
            {
                "item_id": "material-only",
                "colors": ["红色"],
                "category": "配饰",
                "sub_category": "手链",
                "style": ["复古"],
                "details": ["圆环"],
                "scene": ["晚宴"],
                "material": ["棉"],
            },
            {
                "item_id": "no-match",
                "colors": ["黑色"],
                "category": "下装",
                "sub_category": "长裤",
                "style": ["运动"],
                "details": ["抽绳"],
                "scene": ["居家"],
                "material": ["涤纶"],
            },
        ]

        results = module.apply_metadata_rule_weights(
            "蓝色上装衬衫，休闲露肩，适合通勤，棉质",
            fused_results,
            metadata_items,
        )

        expected_fields = {
            "item_id",
            "object_key",
            "retrieval_text",
            "text_rank",
            "image_rank",
            "bm25_rank",
            "rrf_score",
            "sources",
            "rule_score",
            "adjusted_score",
            "matched_fields",
        }
        self.assertTrue(all(set(item) == expected_fields for item in results))
        by_id = {item["item_id"]: item for item in results}
        self.assertEqual(
            by_id["all-fields"]["matched_fields"],
            ["colors", "category", "sub_category", "style", "details", "scene"],
        )
        self.assertNotIn("material", by_id["all-fields"]["matched_fields"])
        self.assertGreater(by_id["all-fields"]["rule_score"], 0)
        self.assertGreaterEqual(
            by_id["all-fields"]["adjusted_score"],
            by_id["all-fields"]["rrf_score"],
        )
        for item_id in ("material-only", "no-match"):
            self.assertEqual(by_id[item_id]["matched_fields"], [])
            self.assertEqual(by_id[item_id]["rule_score"], 0)
            self.assertEqual(
                by_id[item_id]["adjusted_score"],
                by_id[item_id]["rrf_score"],
            )
        ordering = [
            (item["adjusted_score"], item["rrf_score"])
            for item in results
        ]
        self.assertEqual(ordering, sorted(ordering, reverse=True))

    def test_中文查询使用两个新_collection_并归一化_chroma结果(self):
        module = import_required("src.polyvore_retrieval")
        text_collection = FakeCollection(
            {
                "ids": [["shared", "text-only"]],
                "documents": [["蓝色休闲连衣裙", "白色通勤衬衫"]],
                "metadatas": [[
                    {
                        "item_id": "shared",
                        "object_key": "polyvore/items/shared.jpg",
                    },
                    {
                        "item_id": "text-only",
                        "object_key": "polyvore/items/text-only.jpg",
                    },
                ]],
            }
        )
        image_collection = FakeCollection(
            {
                "ids": [["image-only", "shared"]],
                "documents": [["蓝色运动外套", "蓝色休闲连衣裙"]],
                "metadatas": [[
                    {
                        "item_id": "image-only",
                        "object_key": "polyvore/items/image-only.jpg",
                        "retrieval_text": "蓝色运动外套",
                    },
                    {
                        "item_id": "shared",
                        "object_key": "polyvore/items/shared.jpg",
                        "retrieval_text": "蓝色休闲连衣裙",
                    },
                ]],
            }
        )
        chroma_client = FakeChromaClient(
            {
                TEXT_COLLECTION_NAME: text_collection,
                IMAGE_COLLECTION_NAME: image_collection,
            }
        )
        text_embeddings = FakeEmbeddings([0.1] * 1024)
        image_embeddings = FakeEmbeddings([0.2] * 512)

        results = module.retrieve_polyvore_query(
            query="适合夏天的蓝色休闲穿搭",
            chroma_client=chroma_client,
            text_embeddings=text_embeddings,
            image_embeddings=image_embeddings,
            limit=2,
        )

        self.assertEqual(module.TEXT_COLLECTION_NAME, TEXT_COLLECTION_NAME)
        self.assertEqual(module.IMAGE_COLLECTION_NAME, IMAGE_COLLECTION_NAME)
        self.assertEqual(
            chroma_client.requested_names,
            [TEXT_COLLECTION_NAME, IMAGE_COLLECTION_NAME],
        )
        self.assertNotIn("products_text", chroma_client.requested_names)
        self.assertNotIn("products_image", chroma_client.requested_names)
        self.assertEqual(text_embeddings.queries, ["适合夏天的蓝色休闲穿搭"])
        self.assertEqual(image_embeddings.queries, ["适合夏天的蓝色休闲穿搭"])
        self.assertEqual(text_collection.calls[0]["query_embeddings"], [[0.1] * 1024])
        self.assertEqual(image_collection.calls[0]["query_embeddings"], [[0.2] * 512])
        self.assertEqual(text_collection.calls[0]["n_results"], 2)
        self.assertEqual(image_collection.calls[0]["n_results"], 2)
        self.assertEqual(
            results[0],
            {
                "item_id": "shared",
                "object_key": "polyvore/items/shared.jpg",
                "retrieval_text": "蓝色休闲连衣裙",
                "text_rank": 1,
                "image_rank": 2,
                "bm25_rank": None,
                "rrf_score": 1 / 61 + 1 / 62,
                "sources": ["text", "image"],
                "rule_score": 0,
                "adjusted_score": 1 / 61 + 1 / 62,
                "matched_fields": [],
            },
        )

    def test_tools_cli_入口可导入(self):
        module = import_required("tools.cli_polyvore_retrieval")

        self.assertTrue(callable(module.main))


if __name__ == "__main__":
    unittest.main()
