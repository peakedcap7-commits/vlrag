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


def create_client(service):
    """模块存在后才加载 FastAPI 测试客户端。"""
    app_module = import_required("src.api.app")
    from fastapi.testclient import TestClient

    return TestClient(app_module.create_app(service))


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
        self.assertNotIn("products_text", constants)
        self.assertNotIn("products_image", constants)


if __name__ == "__main__":
    unittest.main()
