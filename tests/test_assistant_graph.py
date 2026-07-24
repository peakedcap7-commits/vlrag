import unittest


class FakeService:
    def __init__(self):
        self.calls = []

    def recommend(self, query, top_k, retrieval_limit):
        self.calls.append((query, top_k, retrieval_limit))
        return {"query": query, "anchor": None, "outfit_candidates": []}


class FakeOutfitAnalyzeService:
    def __init__(self):
        self.calls = []

    def analyze(self, image_keys):
        self.calls.append(image_keys)
        return {
            "analysis_stage": "outfit_assessment",
            "score": 82,
            "evidence_level": "strong",
            "graph_evidence": [
                {
                    "item_a": "1",
                    "item_b": "2",
                    "shared_outfit_ids": ["o1"],
                    "cooccurrence_count": 1,
                }
            ],
            "rule_scores": {
                "graph_score": 30,
                "category_score": 20,
                "color_score": 16,
                "style_score": 16,
            },
            "warnings": [],
            "items": [
                {
                    "input_image_key": image_key,
                    "matches": [
                        {
                            "item_id": str(rank),
                            "rank": rank,
                            "score": 0.9,
                            "object_key": f"polyvore/items/{rank}.jpg",
                            "category": "上装",
                            "sub_category": "衬衫",
                            "colors": ["蓝色"],
                            "style": [],
                        }
                        for rank in range(1, 4)
                    ],
                }
                for image_key in image_keys
            ],
        }


class FakeOutfitAdviceService:
    def __init__(self):
        self.calls = []

    def generate(self, analysis):
        self.calls.append(analysis)
        return {
            "verdict": "推荐",
            "summary": "整体搭配协调。",
            "strengths": ["品类互补"],
            "issues": [],
            "suggestions": ["保持当前搭配即可"],
        }


class FakeOutfitReviseService:
    def __init__(self):
        self.calls = []

    def parse(self, message, conversation_state):
        self.calls.append((message, conversation_state))
        return {
            "exclude_categories": ["裙子"],
            "prefer_categories": ["裤子"],
            "keep_items": [],
            "prefer_colors": [],
            "style_shift": None,
            "rewrite_scope": "partial",
        }


class FakeOutfitReviseCandidateService:
    def __init__(self):
        self.calls = []

    def find_replacements(
        self,
        message,
        conversation_state,
        parsed_constraints,
        limit,
    ):
        self.calls.append(
            (message, conversation_state, parsed_constraints, limit)
        )
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
            "message": "已找到符合约束的替换候选。",
        }


class AssistantGraphTest(unittest.TestCase):
    def test_规则路由覆盖五种意图(self):
        from src.assistant_graph import AssistantIntent, classify_intent

        cases = [
            (
                {"message": "", "image_keys": [], "conversation_state": None},
                AssistantIntent.UNSUPPORTED,
            ),
            (
                {
                    "message": "看看这套搭配",
                    "image_keys": ["a.jpg", "b.jpg"],
                    "conversation_state": None,
                },
                AssistantIntent.OUTFIT_ANALYZE,
            ),
            (
                {
                    "message": "不要裙子，换成裤子",
                    "image_keys": [],
                    "conversation_state": {"turn": 1},
                },
                AssistantIntent.OUTFIT_REVISE,
            ),
            (
                {
                    "message": "推荐一套通勤穿搭",
                    "image_keys": [],
                    "conversation_state": None,
                },
                AssistantIntent.SCENE_OUTFIT_GENERATE,
            ),
            (
                {
                    "message": "蓝色裤子搭什么",
                    "image_keys": [],
                    "conversation_state": None,
                },
                AssistantIntent.SINGLE_ITEM_RECOMMEND,
            ),
        ]

        for payload, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_intent(**payload), expected)

    def test_单品节点只透传现有_service(self):
        from src.assistant_graph import build_assistant_graph

        service = FakeService()
        graph = build_assistant_graph(service)

        result = graph.invoke(
            {
                "message": "蓝色裤子搭什么",
                "image_keys": [],
                "conversation_state": None,
                "top_k": 3,
                "retrieval_limit": 4,
            }
        )

        self.assertEqual(service.calls, [("蓝色裤子搭什么", 3, 4)])
        self.assertEqual(result["intent"], "single_item_recommend")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["query"], "蓝色裤子搭什么")

    def test_多图节点调用匹配_service_并返回_ok(self):
        from src.assistant_graph import build_assistant_graph

        service = FakeService()
        outfit_analyze_service = FakeOutfitAnalyzeService()
        outfit_advice_service = FakeOutfitAdviceService()
        graph = build_assistant_graph(
            service,
            outfit_analyze_service,
            outfit_advice_service,
        )

        result = graph.invoke(
            {
                "message": "分析这两件",
                "image_keys": ["a.jpg", "b.jpg"],
                "conversation_state": None,
                "top_k": 5,
                "retrieval_limit": 5,
            }
        )

        self.assertEqual(service.calls, [])
        self.assertEqual(
            outfit_analyze_service.calls,
            [["a.jpg", "b.jpg"]],
        )
        self.assertEqual(len(outfit_advice_service.calls), 1)
        self.assertEqual(result["intent"], "outfit_analyze")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["verdict"], "推荐")
        self.assertNotIn("graph_evidence", result["result"])
        self.assertNotIn("rule_scores", result["result"])

    def test_单图仍路由到单品推荐(self):
        from src.assistant_graph import AssistantIntent, classify_intent

        self.assertEqual(
            classify_intent("", ["uploads/demo/1.jpg"], None),
            AssistantIntent.SINGLE_ITEM_RECOMMEND,
        )

    def test_缺少建议_service_时不暴露内部技术结果(self):
        from src.assistant_graph import build_assistant_graph

        graph = build_assistant_graph(
            FakeService(),
            FakeOutfitAnalyzeService(),
        )

        result = graph.invoke(
            {
                "message": "分析这两件",
                "image_keys": ["a.jpg", "b.jpg"],
                "conversation_state": None,
                "top_k": 5,
                "retrieval_limit": 5,
            }
        )

        self.assertEqual(result["status"], "not_ready")
        self.assertIsNone(result["result"])

    def test_改搭节点返回结构化约束(self):
        from src.assistant_graph import build_assistant_graph

        revise_service = FakeOutfitReviseService()
        graph = build_assistant_graph(
            FakeService(),
            outfit_revise_service=revise_service,
        )
        conversation_state = {
            "anchor_item_id": "1",
            "candidate_item_ids": ["2"],
        }

        result = graph.invoke(
            {
                "message": "不要裙子，换成裤子",
                "image_keys": [],
                "conversation_state": conversation_state,
                "top_k": 5,
                "retrieval_limit": 5,
            }
        )

        self.assertEqual(
            revise_service.calls,
            [("不要裙子，换成裤子", conversation_state)],
        )
        self.assertEqual(result["intent"], "outfit_revise")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["prefer_categories"], ["裤子"])

    def test_改搭节点调用候选召回并合并结果(self):
        from src.assistant_graph import build_assistant_graph

        revise_service = FakeOutfitReviseService()
        candidate_service = FakeOutfitReviseCandidateService()
        graph = build_assistant_graph(
            FakeService(),
            outfit_revise_service=revise_service,
            outfit_revise_candidate_service=candidate_service,
        )
        conversation_state = {"candidate_item_ids": ["1"]}

        result = graph.invoke(
            {
                "message": "不要裙子，换成裤子",
                "image_keys": [],
                "conversation_state": conversation_state,
                "top_k": 5,
                "retrieval_limit": 3,
            }
        )

        self.assertEqual(len(candidate_service.calls), 1)
        self.assertEqual(candidate_service.calls[0][0], "不要裙子，换成裤子")
        self.assertEqual(candidate_service.calls[0][1], conversation_state)
        self.assertEqual(candidate_service.calls[0][3], 3)
        self.assertEqual(
            result["result"]["replacement_candidates"][0]["item_id"],
            "pants",
        )
        self.assertEqual(
            result["response_message"],
            "已找到符合约束的替换候选。",
        )

    def test_改搭需要追问时不调用候选召回(self):
        from src.assistant_graph import build_assistant_graph

        class ClarifyingReviseService:
            def parse(self, _message, _state):
                return {
                    "needs_clarification": True,
                    "clarification_question": "请先选择要替换的商品。",
                    "replacement_candidates": [],
                }

        candidate_service = FakeOutfitReviseCandidateService()
        graph = build_assistant_graph(
            FakeService(),
            outfit_revise_service=ClarifyingReviseService(),
            outfit_revise_candidate_service=candidate_service,
        )

        result = graph.invoke(
            {
                "message": "换掉这个",
                "image_keys": [],
                "conversation_state": {"candidate_item_ids": ["1", "2"]},
                "top_k": 5,
                "retrieval_limit": 3,
            }
        )

        self.assertEqual(candidate_service.calls, [])
        self.assertEqual(result["result"]["replacement_candidates"], [])
        self.assertEqual(
            result["response_message"],
            "请先选择要替换的商品。",
        )

    def test_改搭缺少上下文时返回明确提示(self):
        from src.assistant_graph import build_assistant_graph

        graph = build_assistant_graph(
            FakeService(),
            outfit_revise_service=FakeOutfitReviseService(),
        )

        result = graph.invoke(
            {
                "message": "不要裙子，换成裤子",
                "image_keys": [],
                "conversation_state": None,
                "top_k": 5,
                "retrieval_limit": 5,
            }
        )

        self.assertEqual(result["intent"], "outfit_revise")
        self.assertEqual(result["status"], "not_ready")
        self.assertIsNone(result["result"])
        self.assertIn("conversation_state", result["response_message"])

    def test_重新搭一套路由到改搭(self):
        from src.assistant_graph import AssistantIntent, classify_intent

        self.assertEqual(
            classify_intent(
                "重新搭一套",
                [],
                {"candidate_item_ids": ["1", "2"]},
            ),
            AssistantIntent.OUTFIT_REVISE,
        )


if __name__ == "__main__":
    unittest.main()
