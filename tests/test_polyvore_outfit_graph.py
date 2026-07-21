import importlib
import unittest


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


OUTFITS = [
    {
        "set_id": "outfit-2",
        "items": [
            {"item_id": "anchor"},
            {"item_id": "candidate-shared"},
            {"item_id": "candidate-two"},
        ],
    },
    {
        "set_id": "outfit-1",
        "items": [
            {"item_id": "candidate-shared"},
            {"item_id": "anchor"},
            {"item_id": "candidate-one"},
        ],
    },
    {
        "set_id": "outfit-3",
        "items": [
            {"item_id": "candidate-two"},
            {"item_id": "anchor"},
        ],
    },
]


class PolyvoreOutfitGraphTest(unittest.TestCase):
    def test_构建双向索引并合并多个_outfit_共现(self):
        module = import_required("src.graph.polyvore_outfit_graph")

        item_to_outfit_ids, outfit_to_item_ids = module.build_outfit_indexes(OUTFITS)
        results = module.query_outfit_candidates(
            "anchor",
            item_to_outfit_ids,
            outfit_to_item_ids,
        )

        self.assertEqual(
            item_to_outfit_ids["anchor"],
            ["outfit-1", "outfit-2", "outfit-3"],
        )
        self.assertEqual(
            outfit_to_item_ids["outfit-1"],
            ["anchor", "candidate-one", "candidate-shared"],
        )
        self.assertNotIn("anchor", [item["candidate_item_id"] for item in results])
        self.assertTrue(
            all(
                set(item)
                == {
                    "anchor_item_id",
                    "candidate_item_id",
                    "shared_outfit_ids",
                    "cooccurrence_count",
                }
                for item in results
            )
        )
        self.assertEqual(
            results,
            [
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "candidate-shared",
                    "shared_outfit_ids": ["outfit-1", "outfit-2"],
                    "cooccurrence_count": 2,
                },
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "candidate-two",
                    "shared_outfit_ids": ["outfit-2", "outfit-3"],
                    "cooccurrence_count": 2,
                },
                {
                    "anchor_item_id": "anchor",
                    "candidate_item_id": "candidate-one",
                    "shared_outfit_ids": ["outfit-1"],
                    "cooccurrence_count": 1,
                },
            ],
        )

    def test_未知_item_返回空列表(self):
        module = import_required("src.graph.polyvore_outfit_graph")
        item_to_outfit_ids, outfit_to_item_ids = module.build_outfit_indexes(OUTFITS)

        results = module.query_outfit_candidates(
            "unknown",
            item_to_outfit_ids,
            outfit_to_item_ids,
        )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
