import json
import unittest


class FakeRecommendService:
    def recommend(self, *_args):
        return {"query": "", "anchor": None, "outfit_candidates": []}


class FakeReviseService:
    def parse(self, _message, _state):
        return {
            "exclude_categories": ["裙子"],
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
            "ranking_context": {},
            "message": "已找到符合约束的替换候选。",
        }


class FakeGraphService:
    def validate_and_rank(self, candidates, *_args):
        item = dict(candidates[0])
        item["match_level"] = "strong"
        item["reason"] = "更适合作为当前搭配的替换单品。"
        return [item]


class FakeAdviceService:
    def __init__(self):
        self.calls = []

    def generate(self, revise_result, conversation_state):
        self.calls.append((revise_result, conversation_state))
        return {
            "verdict": "建议替换",
            "summary": "蓝色牛仔裤更符合你的改搭方向。",
            "changes": ["将裙子换成蓝色牛仔裤"],
            "suggestions": ["保留当前上衣"],
        }


class FailingLlm:
    def invoke(self, _prompt):
        raise TimeoutError("外部服务超时")


class IdLeakingLlm:
    def invoke(self, _prompt):
        payload = {
            "verdict": "建议改搭",
            "summary": "保留物品 199614803，换成更正式的裤装。",
            "changes": ["裙子换成裤子"],
            "suggestions": ["保留 199614803"],
        }
        return type(
            "Response",
            (),
            {"content": json.dumps(payload, ensure_ascii=False)},
        )()


class OutfitReviseAdviceIntegrationTest(unittest.TestCase):
    def test_LangGraph_返回用户建议且不暴露候选技术结果(self):
        from src.assistant_graph import build_assistant_graph

        advice_service = FakeAdviceService()
        graph = build_assistant_graph(
            FakeRecommendService(),
            outfit_revise_service=FakeReviseService(),
            outfit_revise_candidate_service=FakeCandidateService(),
            outfit_revise_graph_service=FakeGraphService(),
            outfit_revise_advice_service=advice_service,
        )

        result = graph.invoke(
            {
                "message": "不要裙子，换成裤子",
                "image_keys": [],
                "conversation_state": {"anchor_item_id": "top"},
                "top_k": 5,
                "retrieval_limit": 3,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            set(result["result"]),
            {"verdict", "summary", "changes", "suggestions"},
        )
        self.assertNotIn("replacement_candidates", result["result"])
        self.assertEqual(len(advice_service.calls), 1)

    def test_公开响应模型支持四字段建议并拒绝图技术字段(self):
        from pydantic import ValidationError

        from src.api.schemas import OutfitReviseAdviceResult

        payload = {
            "verdict": "建议替换",
            "summary": "搭配方向清晰。",
            "changes": ["更换下装"],
            "suggestions": ["保留上衣"],
        }
        result = OutfitReviseAdviceResult.model_validate(payload)
        self.assertEqual(result.verdict, "建议替换")

        with self.assertRaises(ValidationError):
            OutfitReviseAdviceResult.model_validate(
                {**payload, "graph_score": 10}
            )

    def test_advice_超时时_API_返回_fallback_而不是_500(self):
        from fastapi.testclient import TestClient

        from src.api.app import create_app
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        app = create_app(
            service=FakeRecommendService(),
            outfit_revise_service=FakeReviseService(),
            outfit_revise_candidate_service=FakeCandidateService(),
            outfit_revise_graph_service=FakeGraphService(),
            outfit_revise_advice_service=OutfitReviseAdviceService(
                FailingLlm()
            ),
        )
        with TestClient(app) as client:
            response = client.post(
                "/assistant/message",
                json={
                    "message": "换成裤子",
                    "conversation_state": {
                        "anchor_item_id": "top",
                    },
                    "top_k": 5,
                    "retrieval_limit": 3,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(
            set(response.json()["result"]),
            {"verdict", "summary", "changes", "suggestions"},
        )

    def test_API_改搭建议使用用户描述且不暴露内部标识(self):
        from fastapi.testclient import TestClient

        from src.api.app import create_app
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        app = create_app(
            service=FakeRecommendService(),
            outfit_revise_service=FakeReviseService(),
            outfit_revise_candidate_service=FakeCandidateService(),
            outfit_revise_graph_service=FakeGraphService(),
            outfit_revise_advice_service=OutfitReviseAdviceService(
                IdLeakingLlm()
            ),
        )
        with TestClient(app) as client:
            response = client.post(
                "/assistant/message",
                json={
                    "message": "不要裙子，换成裤子，整体更正式一点",
                    "conversation_state": {
                        "anchor_item_id": "199614803",
                        "locked_item_ids": ["199614803"],
                        "item_metadata": [
                            {
                                "item_id": "199614803",
                                "category": "上衣",
                                "sub_category": "衬衫",
                                "colors": ["蓝色"],
                            }
                        ],
                    },
                    "top_k": 5,
                    "retrieval_limit": 3,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        public_text = json.dumps(
            response.json()["result"],
            ensure_ascii=False,
        )
        self.assertIn("当前蓝色衬衫", public_text)
        self.assertNotIn("199614803", public_text)
        self.assertNotIn("item_id", public_text)
        self.assertNotIn("object_key", public_text)


if __name__ == "__main__":
    unittest.main()
