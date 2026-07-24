import unittest


class FakeOutfitProvider:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def query_replacement_cooccurrences(
        self,
        retained_item_ids,
        candidate_item_ids,
    ):
        self.calls.append((retained_item_ids, candidate_item_ids))
        return list(self.rows)


def candidate(item_id, category="", colors=None, style=None):
    return {
        "item_id": item_id,
        "object_key": f"polyvore/items/{item_id}.jpg",
        "category": category,
        "sub_category": "",
        "colors": colors or [],
        "style": style or [],
    }


class OutfitReviseGraphServiceTest(unittest.TestCase):
    def test_图共现优先_其次元数据偏好_最后文本召回顺序(self):
        from src.outfit_revise_graph_service import (
            OutfitReviseGraphService,
        )

        provider = FakeOutfitProvider(
            [
                {
                    "retained_item_id": "top",
                    "candidate_item_id": "graph",
                    "shared_outfit_ids": ["outfit-1"],
                    "cooccurrence_count": 1,
                }
            ]
        )
        service = OutfitReviseGraphService(provider)

        result = service.validate_and_rank(
            [
                candidate("weak", "配饰"),
                candidate("medium", "下装", ["蓝色"]),
                candidate("graph", "配饰"),
            ],
            {
                "anchor_item_id": "anchor",
                "locked_item_ids": ["top"],
            },
            {
                "prefer_categories": ["裤子"],
                "prefer_colors": ["蓝色"],
                "bound_keep_item_ids": ["kept"],
                "needs_clarification": False,
            },
            {
                "weak": {"text_rank": 0},
                "medium": {"text_rank": 2},
                "graph": {"text_rank": 1},
            },
        )

        self.assertEqual(
            provider.calls,
            [(["top", "kept", "anchor"], ["weak", "medium", "graph"])],
        )
        self.assertEqual(
            [item["item_id"] for item in result],
            ["graph", "medium", "weak"],
        )
        self.assertEqual(
            [item["match_level"] for item in result],
            ["strong", "medium", "weak"],
        )
        self.assertEqual(
            result[0]["reason"],
            "更适合作为当前搭配的替换单品。",
        )
        self.assertEqual(
            result[1]["reason"],
            "符合你的替换方向，整体风格较接近。",
        )
        self.assertEqual(
            result[2]["reason"],
            "符合基础条件，但当前数据中缺少明确搭配证据。",
        )
        for item in result:
            self.assertNotIn("shared_outfit_ids", item)
            self.assertNotIn("graph_score", item)
            self.assertNotIn("rule_scores", item)

    def test_需要追问时不查询图数据库(self):
        from src.outfit_revise_graph_service import (
            OutfitReviseGraphService,
        )

        provider = FakeOutfitProvider()
        result = OutfitReviseGraphService(provider).validate_and_rank(
            [candidate("unused")],
            {"anchor_item_id": "anchor"},
            {"needs_clarification": True},
        )

        self.assertEqual(result, [])
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
