import unittest


class FakeRetrieval:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, query, limit):
        self.calls.append((query, limit))
        return list(self.results)


def resolved_item(
    item_id,
    category,
    sub_category,
    colors=None,
    style=None,
):
    return {
        "found": True,
        "item_id": item_id,
        "bucket": "shopping-qna",
        "object_key": f"polyvore/items/{item_id}.jpg",
        "retrieval_text": "",
        "category": category,
        "sub_category": sub_category,
        "colors": colors or [],
        "style": style or [],
        "scene": [],
    }


class OutfitReviseCandidateServiceTest(unittest.TestCase):
    def test_构造中文查询并过滤排除与锁定商品(self):
        from src.outfit_revise_candidate_service import (
            OutfitReviseCandidateService,
        )

        retrieval = FakeRetrieval(
            [
                {"item_id": "locked"},
                {"item_id": "excluded"},
                {"item_id": "bound-excluded"},
                {"item_id": "skirt"},
                {"item_id": "blue-jeans"},
            ]
        )
        resolved = {
            "locked": resolved_item("locked", "下装", "牛仔裤", ["蓝色"]),
            "excluded": resolved_item(
                "excluded",
                "下装",
                "牛仔裤",
                ["蓝色"],
            ),
            "bound-excluded": resolved_item(
                "bound-excluded",
                "下装",
                "牛仔裤",
                ["蓝色"],
            ),
            "skirt": resolved_item("skirt", "下装", "半身裙", ["蓝色"]),
            "blue-jeans": resolved_item(
                "blue-jeans",
                "下装",
                "牛仔裤",
                ["蓝色"],
                ["正式"],
            ),
        }
        service = OutfitReviseCandidateService(
            retrieval=retrieval,
            resolver=lambda item_id: resolved[item_id],
        )
        parsed = {
            "exclude_categories": ["裙子"],
            "prefer_categories": ["裤子"],
            "prefer_colors": ["蓝色"],
            "style_shift": "more_formal",
            "bound_exclude_item_ids": ["bound-excluded"],
            "needs_clarification": False,
        }

        result = service.find_replacements(
            message="不要半身裙，换成蓝色牛仔裤，更正式一点",
            conversation_state={
                "locked_item_ids": ["locked"],
                "excluded_item_ids": ["excluded"],
            },
            parsed_constraints=parsed,
            limit=5,
        )

        self.assertEqual(retrieval.calls, [("裤子 蓝色 正式", 5)])
        self.assertEqual(
            [item["item_id"] for item in result["replacement_candidates"]],
            ["blue-jeans"],
        )
        self.assertEqual(
            set(result["replacement_candidates"][0]),
            {
                "item_id",
                "object_key",
                "category",
                "sub_category",
                "colors",
                "style",
            },
        )

    def test_偏好匹配候选优先但不执行最终搭配排序(self):
        from src.outfit_revise_candidate_service import (
            OutfitReviseCandidateService,
        )

        retrieval = FakeRetrieval(
            [{"item_id": "red-pants"}, {"item_id": "blue-pants"}]
        )
        resolved = {
            "red-pants": resolved_item(
                "red-pants",
                "下装",
                "长裤",
                ["红色"],
            ),
            "blue-pants": resolved_item(
                "blue-pants",
                "下装",
                "长裤",
                ["蓝色"],
            ),
        }
        service = OutfitReviseCandidateService(
            retrieval,
            lambda item_id: resolved[item_id],
        )

        result = service.find_replacements(
            "换成蓝色裤子",
            {},
            {
                "exclude_categories": [],
                "prefer_categories": ["裤子"],
                "prefer_colors": ["蓝色"],
                "style_shift": None,
                "bound_exclude_item_ids": [],
                "needs_clarification": False,
            },
            2,
        )

        self.assertEqual(
            [item["item_id"] for item in result["replacement_candidates"]],
            ["blue-pants", "red-pants"],
        )
        self.assertEqual(
            result["ranking_context"],
            {
                "red-pants": {"preference_score": 3, "text_rank": 0},
                "blue-pants": {"preference_score": 5, "text_rank": 1},
            },
        )

    def test_需要追问时不触发召回(self):
        from src.outfit_revise_candidate_service import (
            OutfitReviseCandidateService,
        )

        retrieval = FakeRetrieval([{"item_id": "unused"}])
        service = OutfitReviseCandidateService(
            retrieval,
            lambda _item_id: {},
        )

        result = service.find_replacements(
            "换掉这个",
            {},
            {
                "needs_clarification": True,
                "clarification_question": "请先选择要替换的商品。",
            },
            3,
        )

        self.assertEqual(retrieval.calls, [])
        self.assertEqual(result["replacement_candidates"], [])
        self.assertEqual(result["message"], "请先选择要替换的商品。")

    def test_过滤后无候选返回清晰提示(self):
        from src.outfit_revise_candidate_service import (
            OutfitReviseCandidateService,
        )

        retrieval = FakeRetrieval([{"item_id": "locked"}])
        service = OutfitReviseCandidateService(
            retrieval,
            lambda item_id: resolved_item(
                item_id,
                "下装",
                "长裤",
            ),
        )

        result = service.find_replacements(
            "换成裤子",
            {"locked_item_ids": ["locked"]},
            {
                "exclude_categories": [],
                "prefer_categories": ["裤子"],
                "prefer_colors": [],
                "style_shift": None,
                "bound_exclude_item_ids": [],
                "needs_clarification": False,
            },
            3,
        )

        self.assertEqual(result["replacement_candidates"], [])
        self.assertIn("暂未找到", result["message"])


if __name__ == "__main__":
    unittest.main()
