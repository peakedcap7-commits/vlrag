import ast
import importlib
import unittest
from pathlib import Path


def import_required(module_name):
    """把待实现模块缺失报告为预期的契约失败。"""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"缺少待实现模块：{module_name}") from exc


class FakeRetrieval:
    """记录检索数量，不加载向量模型。"""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, query, limit):
        self.calls.append((query, limit))
        return self.results


class FakeOutfitProvider:
    """记录 Neo4j outfit 查询参数。"""

    def __init__(self):
        self.calls = []
        self.closed = False

    def query(self, anchor_item_id, top_k):
        self.calls.append((anchor_item_id, top_k))
        return []

    def close(self):
        self.closed = True


class PolyvoreRecommendServiceTest(unittest.TestCase):
    def test_默认_valid_path_使用_nondisjoint_数据集(self):
        module = import_required("src.polyvore_recommend_service")

        config = module.PolyvoreRecommendConfig()

        self.assertEqual(
            config.valid_path,
            Path(r"D:\datasets\polyvore-outfits\nondisjoint\valid.json"),
        )
        self.assertEqual(
            config.neo4j_manifest_path,
            Path("data/processed/polyvore_neo4j_items_manifest.jsonl"),
        )
        self.assertEqual(
            config.retrieval_manifest_path,
            Path("data/processed/polyvore_neo4j_items_retrieval.jsonl"),
        )
        self.assertEqual(config.outfit_provider, "neo4j")

    def test_recommend_只编排注入依赖并透传三个请求参数(self):
        module = import_required("src.polyvore_recommend_service")
        retrieval = FakeRetrieval(
            [
                {
                    "item_id": "anchor",
                    "object_key": "polyvore/items/anchor.jpg",
                    "retrieval_text": "蓝色休闲衬衫",
                    "sources": ["text", "bm25"],
                    "rrf_score": 0.03,
                    "rule_score": 0.2,
                    "adjusted_score": 0.23,
                }
            ]
        )
        outfit_provider = FakeOutfitProvider()

        service = module.PolyvoreRecommendService(
            retrieval=retrieval,
            outfit_provider=outfit_provider,
            resolver=lambda item_id: {"found": True, "item_id": item_id},
        )

        result = service.recommend(
            query="蓝色休闲穿搭",
            top_k=5,
            retrieval_limit=3,
        )

        self.assertEqual(retrieval.calls, [("蓝色休闲穿搭", 3)])
        self.assertEqual(outfit_provider.calls, [("anchor", 5)])
        self.assertEqual(result["query"], "蓝色休闲穿搭")
        self.assertEqual(result["anchor"]["item_id"], "anchor")
        self.assertTrue(result["anchor"]["resolved"]["found"])
        self.assertEqual(result["outfit_candidates"], [])

        service.close()
        self.assertTrue(outfit_provider.closed)

    def test_api_与_cli_共同从_service模块导入_builder(self):
        project_root = Path(__file__).resolve().parents[1]
        api_path = project_root / "src/api/app.py"
        cli_path = project_root / "tools/cli_polyvore_recommend.py"
        self.assertTrue(api_path.exists(), "缺少 API app 模块")

        def imported_names(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return {
                (node.module, alias.name)
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }

        expected = (
            "src.polyvore_recommend_service",
            "build_polyvore_recommend_service",
        )
        self.assertIn(expected, imported_names(api_path))
        self.assertIn(expected, imported_names(cli_path))

    def test_service_不再导入内存_outfit_graph(self):
        project_root = Path(__file__).resolve().parents[1]
        source = (project_root / "src/polyvore_recommend_service.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("polyvore_outfit_graph", source)
        self.assertIn("neo4j_outfit_provider", source)


if __name__ == "__main__":
    unittest.main()
