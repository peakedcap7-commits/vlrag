import json
import unittest


class FakeResponse:
    content = '{"verdict":"可尝试","summary":"整体协调","strengths":[],"issues":[],"suggestions":[]}'


class FakeLlm:
    def invoke(self, _prompt):
        return FakeResponse()


class FakeService:
    def recommend(self, _query, _top_k, _retrieval_limit):
        return {"query": "测试", "anchor": None, "outfit_candidates": []}

    def close(self):
        pass


class FakeResult:
    def __iter__(self):
        return iter([])


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, _query, **_parameters):
        return FakeResult()


class FakeDriver:
    def session(self):
        return FakeSession()

    def close(self):
        pass


def performance_records(log_output):
    records = []
    for line in log_output:
        message = line.split(":", 2)[-1]
        records.append(json.loads(message))
    return records


class PerformanceObservabilityTest(unittest.TestCase):
    def test_measure_输出结构化毫秒日志(self):
        from src.performance import measure

        with self.assertLogs("shopping_qna.performance", level="INFO") as logs:
            with measure("clip_embed_ms", operation="test"):
                pass

        record = performance_records(logs.output)[0]
        self.assertEqual(record["event"], "performance")
        self.assertEqual(record["metric"], "clip_embed_ms")
        self.assertGreaterEqual(record["duration_ms"], 0)
        self.assertEqual(record["operation"], "test")

    def test_api_记录总耗时且响应契约不变(self):
        from fastapi.testclient import TestClient

        from src.api.app import create_app

        with self.assertLogs("shopping_qna.performance", level="INFO") as logs:
            with TestClient(create_app(service=FakeService())) as client:
                response = client.post(
                    "/polyvore/recommend",
                    json={
                        "query": "测试",
                        "top_k": 3,
                        "retrieval_limit": 2,
                    },
                )

        self.assertEqual(
            response.json(),
            {"query": "测试", "anchor": None, "outfit_candidates": []},
        )
        records = performance_records(logs.output)
        self.assertTrue(
            any(
                record["metric"] == "total_ms"
                and record["path"] == "/polyvore/recommend"
                for record in records
            )
        )

    def test_文本建议记录_llm_耗时(self):
        from src.outfit_advice_service import OutfitAdviceService

        analysis = {
            "score": 50,
            "evidence_level": "medium",
            "graph_evidence": [],
            "rule_scores": {},
            "warnings": [],
            "items": [
                {
                    "matches": [
                        {
                            "category": "上衣",
                            "sub_category": "衬衫",
                            "colors": ["蓝色"],
                            "style": [],
                        }
                    ]
                }
            ],
        }
        with self.assertLogs("shopping_qna.performance", level="INFO") as logs:
            OutfitAdviceService(FakeLlm()).generate(analysis)

        records = performance_records(logs.output)
        self.assertTrue(
            any(record["metric"] == "llm_ms" for record in records)
        )

    def test_Neo4j_只读查询记录耗时(self):
        from src.graph.neo4j_outfit_provider import Neo4jOutfitProvider

        provider = Neo4jOutfitProvider(driver=FakeDriver())
        with self.assertLogs("shopping_qna.performance", level="INFO") as logs:
            provider.query("anchor", 3)

        records = performance_records(logs.output)
        self.assertTrue(
            any(record["metric"] == "neo4j_query_ms" for record in records)
        )


if __name__ == "__main__":
    unittest.main()
