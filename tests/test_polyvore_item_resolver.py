import importlib
import json
import tempfile
import unittest
from pathlib import Path


RESOLVED_FIELDS = {
    "found",
    "item_id",
    "bucket",
    "object_key",
    "retrieval_text",
    "category",
    "sub_category",
    "colors",
    "style",
    "scene",
}


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


class PolyvoreItemResolverTest(unittest.TestCase):
    def test_内存索引合并_enriched_并严格解析已知与未知_item(self):
        module = import_required("src.data.polyvore_item_resolver")
        base_index = module.build_item_index(
            records=[
                {
                    "item_id": "known",
                    "bucket": "shopping-qna",
                    "object_key": "polyvore/items/known.jpg",
                    "retrieval_text": "旧检索文本",
                    "category": "",
                }
            ]
        )
        enriched_index = module.build_item_index(
            records=[
                {
                    "item_id": "known",
                    "retrieval_text": "蓝色休闲衬衫",
                    "category": "上装",
                    "sub_category": "衬衫",
                    "colors": ["蓝色"],
                    "style": ["休闲"],
                    "scene": ["通勤"],
                }
            ]
        )

        known = module.resolve_item("known", base_index, enriched_index)
        unknown = module.resolve_item("unknown", base_index, enriched_index)

        self.assertEqual(set(known), RESOLVED_FIELDS)
        self.assertTrue(known["found"])
        self.assertEqual(known["item_id"], "known")
        self.assertEqual(known["object_key"], "polyvore/items/known.jpg")
        self.assertEqual(known["retrieval_text"], "蓝色休闲衬衫")
        self.assertEqual(known["category"], "上装")
        self.assertEqual(known["sub_category"], "衬衫")
        self.assertEqual(known["colors"], ["蓝色"])
        self.assertEqual(known["style"], ["休闲"])
        self.assertEqual(known["scene"], ["通勤"])
        self.assertEqual(set(unknown), RESOLVED_FIELDS)
        self.assertFalse(unknown["found"])
        self.assertEqual(unknown["item_id"], "unknown")

    def test_临时_jsonl_可构建索引且不访问外部服务(self):
        module = import_required("src.data.polyvore_item_resolver")
        record = {
            "item_id": "jsonl-item",
            "bucket": "shopping-qna",
            "object_key": "polyvore/items/jsonl-item.jpg",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.jsonl"
            path.write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            item_index = module.build_item_index(jsonl_path=path)

        resolved = module.resolve_item("jsonl-item", item_index)

        self.assertTrue(resolved["found"])
        self.assertEqual(resolved["object_key"], record["object_key"])
        self.assertEqual(set(resolved), RESOLVED_FIELDS)

    def test_neo4j_manifest兜底图片且_enriched仍优先(self):
        module = import_required("src.data.polyvore_item_resolver")
        neo4j_index = module.build_item_index(
            records=[
                {
                    "item_id": "candidate",
                    "bucket": "shopping-qna",
                    "object_key": "polyvore/items/candidate.jpg",
                    "category": "基础类别",
                }
            ]
        )
        sample_index = module.build_item_index(records=[])
        enriched_index = module.build_item_index(
            records=[{"item_id": "candidate", "category": "增强类别"}]
        )

        base_index = module.merge_item_indexes(neo4j_index, sample_index)
        resolved = module.resolve_item("candidate", base_index, enriched_index)

        self.assertTrue(resolved["found"])
        self.assertEqual(resolved["object_key"], "polyvore/items/candidate.jpg")
        self.assertEqual(resolved["category"], "增强类别")


if __name__ == "__main__":
    unittest.main()
