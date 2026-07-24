import ast
import importlib
import unittest
from pathlib import Path


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块或运行依赖：{module_name}") from exc


class FakeService:
    """返回完整 resolved 结构并记录 API 入参。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def recommend(self, query, top_k, retrieval_limit):
        self.calls.append((query, top_k, retrieval_limit))
        return self.result


class FakeOutfitAnalyzeService:
    def analyze(self, image_keys):
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
    def generate(self, _analysis):
        return {
            "verdict": "推荐",
            "summary": "整体搭配协调。",
            "strengths": ["品类互补"],
            "issues": [],
            "suggestions": ["保持当前搭配即可"],
        }


class FakeOutfitReviseCandidateService:
    def find_replacements(
        self,
        _message,
        _conversation_state,
        _parsed_constraints,
        _limit,
    ):
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


def api_result(query="蓝色休闲穿搭"):
    """构造 API 成功响应。"""
    resolved = {
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
    }
    return {
        "query": query,
        "anchor": {
            "item_id": "anchor",
            "object_key": "polyvore/items/anchor.jpg",
            "retrieval_text": "蓝色休闲衬衫",
            "sources": ["text", "bm25"],
            "rrf_score": 0.03,
            "rule_score": 0.2,
            "adjusted_score": 0.23,
            "resolved": resolved,
        },
        "outfit_candidates": [],
    }


def create_client(
    service,
    outfit_analyze_service=None,
    outfit_advice_service=None,
    outfit_revise_service=None,
    outfit_revise_candidate_service=None,
):
    """模块存在后才加载 FastAPI 测试客户端。"""
    app_module = import_required("src.api.app")
    from fastapi.testclient import TestClient

    return TestClient(
        app_module.create_app(
            service,
            outfit_analyze_service=outfit_analyze_service,
            outfit_advice_service=outfit_advice_service,
            outfit_revise_service=outfit_revise_service,
            outfit_revise_candidate_service=outfit_revise_candidate_service,
        )
    )


class PolyvoreApiTest(unittest.TestCase):
    def test_health_返回_200(self):
        client = create_client(FakeService(api_result()))

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_recommend_调用_service_并返回_resolved结构(self):
        service = FakeService(api_result())
        client = create_client(service)

        response = client.post(
            "/polyvore/recommend",
            json={"query": "蓝色休闲穿搭", "top_k": 5, "retrieval_limit": 3},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.calls, [("蓝色休闲穿搭", 5, 3)])
        self.assertEqual(response.json(), api_result())
        self.assertTrue(response.json()["anchor"]["resolved"]["found"])

    def test_recommend_空结果仍返回_200(self):
        empty_result = {
            "query": "没有结果",
            "anchor": None,
            "outfit_candidates": [],
        }
        client = create_client(FakeService(empty_result))

        response = client.post(
            "/polyvore/recommend",
            json={"query": "没有结果", "top_k": 5, "retrieval_limit": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), empty_result)

    def test_recommend_非法请求返回_422(self):
        client = create_client(FakeService(api_result()))
        invalid_payloads = [
            {"query": "   ", "top_k": 5, "retrieval_limit": 2},
            {"query": "蓝色", "top_k": 0, "retrieval_limit": 2},
            {"query": "蓝色", "top_k": 51, "retrieval_limit": 2},
            {"query": "蓝色", "top_k": 5, "retrieval_limit": 0},
            {"query": "蓝色", "top_k": 5, "retrieval_limit": 6},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = client.post("/polyvore/recommend", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_assistant_普通文本调用推荐_service(self):
        service = FakeService(api_result("蓝色裤子搭什么"))
        client = create_client(service)

        response = client.post(
            "/assistant/message",
            json={
                "message": "蓝色裤子搭什么",
                "image_keys": [],
                "conversation_state": None,
                "top_k": 5,
                "retrieval_limit": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.calls, [("蓝色裤子搭什么", 5, 3)])
        self.assertEqual(response.json()["intent"], "single_item_recommend")
        self.assertEqual(response.json()["status"], "ok")
        self.assertTrue(response.json()["result"]["anchor"]["resolved"]["found"])

    def test_assistant_场景生成仍返回_not_ready(self):
        service = FakeService(api_result())
        client = create_client(service)
        cases = [
            (
                {
                    "message": "推荐一套通勤穿搭",
                    "image_keys": [],
                    "conversation_state": None,
                    "top_k": 5,
                    "retrieval_limit": 3,
                },
                "scene_outfit_generate",
            ),
        ]

        for payload, intent in cases:
            with self.subTest(intent=intent):
                response = client.post("/assistant/message", json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["intent"], intent)
                self.assertEqual(response.json()["status"], "not_ready")
                self.assertIsNone(response.json()["result"])

        self.assertEqual(service.calls, [])

    def test_assistant_改搭返回结构化约束(self):
        service = FakeService(api_result())
        client = create_client(
            service,
            outfit_revise_candidate_service=(
                FakeOutfitReviseCandidateService()
            ),
        )

        response = client.post(
            "/assistant/message",
            json={
                "message": "不要裙子，换成裤子",
                "conversation_state": {
                    "anchor_item_id": "1",
                    "candidate_item_ids": ["2"],
                    "locked_item_ids": [],
                    "excluded_item_ids": [],
                    "item_metadata": [
                        {
                            "item_id": "1",
                            "category": "下装",
                            "sub_category": "半身裙",
                        }
                    ],
                    "last_intent": "single_item_recommend",
                },
                "top_k": 5,
                "retrieval_limit": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["intent"], "outfit_revise")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["exclude_categories"], ["裙子"])
        self.assertEqual(body["result"]["prefer_categories"], ["裤子"])
        self.assertEqual(body["result"]["bound_exclude_item_ids"], ["1"])
        self.assertFalse(body["result"]["needs_clarification"])
        self.assertEqual(
            body["result"]["replacement_candidates"][0]["item_id"],
            "pants",
        )

    def test_assistant_多图返回每图_top3_匹配(self):
        service = FakeService(api_result())
        client = create_client(
            service,
            FakeOutfitAnalyzeService(),
            FakeOutfitAdviceService(),
        )

        response = client.post(
            "/assistant/message",
            json={
                "message": "分析这两件",
                "image_keys": [
                    "uploads/demo/1.jpg",
                    "uploads/demo/2.jpg",
                ],
                "conversation_state": None,
                "top_k": 5,
                "retrieval_limit": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["intent"], "outfit_analyze")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["verdict"], "推荐")
        self.assertEqual(body["result"]["summary"], "整体搭配协调。")
        self.assertNotIn("graph_evidence", body["result"])
        self.assertNotIn("rule_scores", body["result"])

    def test_assistant_冻结_M2_M3_请求和结果契约(self):
        schemas = import_required("src.api.schemas")

        analyze = schemas.AssistantMessageResponse.model_validate(
            {
                "intent": "outfit_analyze",
                "status": "ok",
                "result": {
                    "verdict": "推荐",
                    "summary": "整体协调。",
                    "strengths": ["品类互补"],
                    "issues": [],
                    "suggestions": ["保持简洁配饰"],
                },
                "message": "分析完成",
            }
        )
        revise = schemas.AssistantMessageResponse.model_validate(
            {
                "intent": "outfit_revise",
                "status": "ok",
                "result": {
                    "exclude_categories": ["裙子"],
                    "prefer_categories": ["裤子"],
                    "keep_items": ["1"],
                    "prefer_colors": ["蓝色"],
                    "style_shift": "more_formal",
                    "rewrite_scope": "partial",
                    "normalized_constraints": {
                        "exclude_categories": ["裙子"],
                        "prefer_categories": ["裤子"],
                        "keep_categories": ["上衣"],
                        "prefer_colors": ["蓝色"],
                        "prefer_styles": ["正式"],
                        "rewrite_scope": "partial",
                    },
                    "bound_keep_item_ids": ["1"],
                    "bound_exclude_item_ids": [],
                    "needs_clarification": False,
                    "clarification_question": "",
                    "confidence": 0.95,
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
                },
                "message": "约束解析完成",
            }
        )

        self.assertEqual(analyze.result.verdict, "推荐")
        self.assertEqual(revise.result.prefer_categories, ["裤子"])
        self.assertEqual(
            revise.result.normalized_constraints.keep_categories,
            ["上衣"],
        )

    def test_assistant_image_keys_最多四个且不可重复(self):
        client = create_client(FakeService(api_result()))
        invalid_payloads = [
            {
                "message": "分析",
                "image_keys": ["1", "2", "3", "4", "5"],
                "top_k": 5,
                "retrieval_limit": 3,
            },
            {
                "message": "分析",
                "image_keys": ["same", "same"],
                "top_k": 5,
                "retrieval_limit": 3,
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = client.post("/assistant/message", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_assistant_conversation_state_拒绝未知字段(self):
        client = create_client(FakeService(api_result()))

        response = client.post(
            "/assistant/message",
            json={
                "message": "换成裤子",
                "conversation_state": {"unknown": "value"},
                "top_k": 5,
                "retrieval_limit": 3,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_assistant_conversation_state_拒绝空白重复和锁定排除冲突(self):
        client = create_client(FakeService(api_result()))
        invalid_states = [
            {"candidate_item_ids": ["1", "1"]},
            {"locked_item_ids": [" "]},
            {
                "locked_item_ids": ["1"],
                "excluded_item_ids": ["1"],
            },
        ]

        for conversation_state in invalid_states:
            with self.subTest(conversation_state=conversation_state):
                response = client.post(
                    "/assistant/message",
                    json={
                        "message": "换成裤子",
                        "conversation_state": conversation_state,
                        "top_k": 5,
                        "retrieval_limit": 3,
                    },
                )
                self.assertEqual(response.status_code, 422)

    def test_assistant_conversation_state_校验商品元数据_id(self):
        schemas = import_required("src.api.schemas")
        valid_state = schemas.ConversationState.model_validate(
            {
                "item_metadata": [
                    {
                        "item_id": "1",
                        "category": "上装",
                        "sub_category": "衬衫",
                    }
                ]
            }
        )
        self.assertEqual(valid_state.item_metadata[0].item_id, "1")

        client = create_client(FakeService(api_result()))
        response = client.post(
            "/assistant/message",
            json={
                "message": "保留上衣",
                "conversation_state": {
                    "item_metadata": [
                        {"item_id": "1", "category": "上衣"},
                        {"item_id": "1", "category": "上衣"},
                    ]
                },
                "top_k": 5,
                "retrieval_limit": 3,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_api_静态不依赖_cli_或旧_collection(self):
        project_root = Path(__file__).resolve().parents[1]
        app_path = project_root / "src/api/app.py"
        self.assertTrue(app_path.exists(), "缺少 API app 模块")
        source = app_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        constants = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

        self.assertFalse(any("cli_" in module for module in imported_modules))
        self.assertFalse(any("neo4j" in module for module in imported_modules))
        self.assertNotIn("products_text", constants)
        self.assertNotIn("products_image", constants)


if __name__ == "__main__":
    unittest.main()
