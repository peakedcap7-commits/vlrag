import importlib
import inspect
import unittest


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


class FakeRetrieval:
    """记录查询并返回纯内存检索结果。"""

    def __init__(self, results):
        self.results = results
        self.queries = []

    def __call__(self, query):
        self.queries.append(query)
        return self.results


class FakeOutfitQuery:
    """记录 anchor 和两个索引，不访问真实图数据。"""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, anchor_item_id, item_to_outfit_ids, outfit_to_item_ids):
        self.calls.append(
            (anchor_item_id, item_to_outfit_ids, outfit_to_item_ids)
        )
        return self.results


class FakeResolver:
    """按 item_id 返回严格解析结果并记录调用。"""

    def __init__(self, resolved_items):
        self.resolved_items = resolved_items
        self.item_ids = []

    def __call__(self, item_id):
        self.item_ids.append(item_id)
        return self.resolved_items[item_id]


def retrieval_item(item_id, adjusted_score):
    """构造包含内部字段的检索项，验证编排层只输出批准字段。"""
    return {
        "item_id": item_id,
        "object_key": f"polyvore/items/{item_id}.jpg",
        "retrieval_text": f"{item_id} 的检索文本",
        "text_rank": 1,
        "image_rank": 2,
        "bm25_rank": None,
        "sources": ["text", "image"],
        "rrf_score": 0.03,
        "rule_score": 0.2,
        "adjusted_score": adjusted_score,
        "matched_fields": ["colors"],
    }


def unresolved_item(item_id):
    """构造未知商品的严格解析结果。"""
    return {
        "found": False,
        "item_id": item_id,
        "bucket": "",
        "object_key": "",
        "retrieval_text": "",
        "category": "",
        "sub_category": "",
        "colors": [],
        "style": [],
        "scene": [],
    }


class PolyvoreRecommendTest(unittest.TestCase):
    def test_注入_resolver_为_anchor_和未知_candidate_附加解析结果(self):
        module = import_required("src.polyvore_recommend")
        self.assertIn(
            "resolver",
            inspect.signature(module.recommend_polyvore_query).parameters,
        )
        retrieval = FakeRetrieval([retrieval_item("anchor", 0.23)])
        outfit_query = FakeOutfitQuery(
            [
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "unknown-1",
                    "shared_outfit_ids": ["outfit-1"],
                    "cooccurrence_count": 1,
                },
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "unknown-2",
                    "shared_outfit_ids": ["outfit-1", "outfit-2"],
                    "cooccurrence_count": 2,
                },
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "unknown-3",
                    "shared_outfit_ids": ["outfit-3"],
                    "cooccurrence_count": 1,
                },
            ]
        )
        resolver = FakeResolver(
            {
                "anchor": {
                    "found": True,
                    "item_id": "anchor",
                    "bucket": "shopping-qna",
                    "object_key": "polyvore/items/anchor.jpg",
                    "retrieval_text": "蓝色休闲衬衫",
                    "category": "上装",
                    "sub_category": "衬衫",
                    "colors": ["蓝色"],
                    "style": ["休闲"],
                    "scene": ["通勤"],
                },
                "unknown-1": unresolved_item("unknown-1"),
                "unknown-2": unresolved_item("unknown-2"),
                "unknown-3": unresolved_item("unknown-3"),
            }
        )

        result = module.recommend_polyvore_query(
            "蓝色休闲穿搭",
            retrieval,
            outfit_query,
            {"anchor": ["outfit-1", "outfit-2", "outfit-3"]},
            {
                "outfit-1": ["anchor", "unknown-1", "unknown-2"],
                "outfit-2": ["anchor", "unknown-2"],
                "outfit-3": ["anchor", "unknown-3"],
            },
            resolver=resolver,
        )

        self.assertEqual(
            resolver.item_ids,
            ["anchor", "unknown-1", "unknown-2", "unknown-3"],
        )
        self.assertEqual(
            set(result["anchor"]),
            {
                "item_id",
                "object_key",
                "retrieval_text",
                "sources",
                "rrf_score",
                "rule_score",
                "adjusted_score",
                "resolved",
            },
        )
        self.assertTrue(result["anchor"]["resolved"]["found"])
        self.assertEqual(len(result["outfit_candidates"]), 3)
        self.assertTrue(
            all(
                set(candidate)
                == {
                    "candidate_item_id",
                    "shared_outfit_ids",
                    "cooccurrence_count",
                    "resolved",
                }
                for candidate in result["outfit_candidates"]
            )
        )
        self.assertEqual(
            result["outfit_candidates"][0]["shared_outfit_ids"],
            ["outfit-1"],
        )
        self.assertEqual(
            result["outfit_candidates"][0]["cooccurrence_count"],
            1,
        )
        self.assertTrue(
            all(
                not candidate["resolved"]["found"]
                for candidate in result["outfit_candidates"]
            )
        )

    def test_top1_item_id_传给_outfit_扩展并裁剪严格输出(self):
        module = import_required("src.polyvore_recommend")
        retrieval = FakeRetrieval(
            [retrieval_item("anchor", 0.23), retrieval_item("second", 0.22)]
        )
        outfit_query = FakeOutfitQuery(
            [
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "anchor",
                    "shared_outfit_ids": ["outfit-1"],
                    "cooccurrence_count": 1,
                },
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "candidate",
                    "shared_outfit_ids": ["outfit-1", "outfit-2"],
                    "cooccurrence_count": 2,
                },
            ]
        )
        item_to_outfit_ids = {"anchor": ["outfit-1", "outfit-2"]}
        outfit_to_item_ids = {
            "outfit-1": ["anchor", "candidate"],
            "outfit-2": ["anchor", "candidate"],
        }

        result = module.recommend_polyvore_query(
            query="蓝色休闲穿搭",
            retrieval=retrieval,
            outfit_query=outfit_query,
            item_to_outfit_ids=item_to_outfit_ids,
            outfit_to_item_ids=outfit_to_item_ids,
        )

        self.assertEqual(retrieval.queries, ["蓝色休闲穿搭"])
        self.assertEqual(
            outfit_query.calls,
            [("anchor", item_to_outfit_ids, outfit_to_item_ids)],
        )
        self.assertEqual(set(result), {"query", "anchor", "outfit_candidates"})
        self.assertEqual(result["query"], "蓝色休闲穿搭")
        self.assertEqual(
            set(result["anchor"]),
            {
                "item_id",
                "object_key",
                "retrieval_text",
                "sources",
                "rrf_score",
                "rule_score",
                "adjusted_score",
            },
        )
        self.assertEqual(result["anchor"]["item_id"], "anchor")
        self.assertEqual(
            result["outfit_candidates"],
            [
                {
                    "candidate_item_id": "candidate",
                    "shared_outfit_ids": ["outfit-1", "outfit-2"],
                    "cooccurrence_count": 2,
                }
            ],
        )

    def test_outfit_无候选时返回空列表(self):
        module = import_required("src.polyvore_recommend")
        retrieval = FakeRetrieval([retrieval_item("anchor", 0.23)])
        outfit_query = FakeOutfitQuery([])

        result = module.recommend_polyvore_query(
            "蓝色休闲穿搭",
            retrieval,
            outfit_query,
            {"anchor": ["outfit-1"]},
            {"outfit-1": ["anchor"]},
        )

        self.assertEqual(result["anchor"]["item_id"], "anchor")
        self.assertEqual(result["outfit_candidates"], [])

    def test_检索为空时不查询_outfit_并返回空锚点(self):
        module = import_required("src.polyvore_recommend")
        retrieval = FakeRetrieval([])
        outfit_query = FakeOutfitQuery(
            [{"candidate_item_id": "不应返回"}]
        )

        result = module.recommend_polyvore_query(
            "不存在的商品",
            retrieval,
            outfit_query,
            {},
            {},
        )

        self.assertEqual(
            result,
            {
                "query": "不存在的商品",
                "anchor": None,
                "outfit_candidates": [],
            },
        )
        self.assertEqual(outfit_query.calls, [])


if __name__ == "__main__":
    unittest.main()
