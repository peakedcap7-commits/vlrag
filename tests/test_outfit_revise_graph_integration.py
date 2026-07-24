import unittest


class FakeRecommendService:
    def recommend(self, *_args):
        return {"query": "", "anchor": None, "outfit_candidates": []}


class FakeReviseService:
    def parse(self, _message, _state):
        return {
            "exclude_categories": [],
            "prefer_categories": ["裤子"],
            "keep_items": [],
            "prefer_colors": [],
            "style_shift": None,
            "rewrite_scope": "partial",
            "bound_keep_item_ids": [],
            "bound_exclude_item_ids": [],
            "needs_clarification": False,
            "clarification_question": "",
            "confidence": 1.0,
        }


class FakeCandidateService:
    def find_replacements(self, *_args):
        return {
            "replacement_candidates": [
                {
                    "item_id": "pants",
                    "object_key": "polyvore/items/pants.jpg",
                    "category": "下装",
                    "sub_category": "牛仔裤",
                    "colors": ["蓝色"],
                    "style": [],
                }
            ],
            "ranking_context": {
                "pants": {"preference_score": 3, "text_rank": 0}
            },
            "message": "已找到符合约束的替换候选。",
        }


class FakeGraphService:
    def __init__(self):
        self.calls = []

    def validate_and_rank(
        self,
        candidates,
        conversation_state,
        parsed_constraints,
        ranking_context,
    ):
        self.calls.append(
            (
                candidates,
                conversation_state,
                parsed_constraints,
                ranking_context,
            )
        )
        item = dict(candidates[0])
        item.update(
            {
                "match_level": "strong",
                "reason": "更适合作为当前搭配的替换单品。",
            }
        )
        return [item]


class OutfitReviseGraphIntegrationTest(unittest.TestCase):
    def test_LangGraph_调用图验证并返回公开字段(self):
        from src.assistant_graph import build_assistant_graph

        graph_service = FakeGraphService()
        graph = build_assistant_graph(
            FakeRecommendService(),
            outfit_revise_service=FakeReviseService(),
            outfit_revise_candidate_service=FakeCandidateService(),
            outfit_revise_graph_service=graph_service,
        )

        result = graph.invoke(
            {
                "message": "换成裤子",
                "image_keys": [],
                "conversation_state": {"anchor_item_id": "top"},
                "top_k": 5,
                "retrieval_limit": 3,
            }
        )

        candidate = result["result"]["replacement_candidates"][0]
        self.assertEqual(candidate["match_level"], "strong")
        self.assertEqual(
            candidate["reason"],
            "更适合作为当前搭配的替换单品。",
        )
        self.assertNotIn("shared_outfit_ids", candidate)
        self.assertEqual(len(graph_service.calls), 1)

    def test_公开响应模型拒绝图数据库技术字段(self):
        from pydantic import ValidationError

        from src.api.schemas import ReplacementCandidate

        payload = {
            "item_id": "pants",
            "object_key": "polyvore/items/pants.jpg",
            "category": "下装",
            "sub_category": "牛仔裤",
            "colors": ["蓝色"],
            "style": [],
            "match_level": "medium",
            "reason": "符合你的替换方向，整体风格较接近。",
        }
        candidate = ReplacementCandidate.model_validate(payload)
        self.assertEqual(candidate.match_level, "medium")

        with self.assertRaises(ValidationError):
            ReplacementCandidate.model_validate(
                {**payload, "shared_outfit_ids": ["outfit-1"]}
            )


if __name__ == "__main__":
    unittest.main()
