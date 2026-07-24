import json
import os
import unittest

import pytest


ANALYSIS = {
    "score": 70,
    "evidence_level": "medium",
    "graph_evidence": [
        {
            "item_a": "1",
            "item_b": "2",
            "shared_outfit_ids": ["o1"],
            "cooccurrence_count": 1,
        }
    ],
    "rule_scores": {
        "graph_score": 20,
        "category_score": 20,
        "color_score": 20,
        "style_score": 10,
    },
    "warnings": ["风格信息不完整，使用中性分"],
    "items": [
        {
            "matches": [
                {
                    "category": "上衣",
                    "sub_category": "衬衫",
                    "colors": ["蓝色"],
                    "style": ["休闲"],
                }
            ]
        },
        {
            "matches": [
                {
                    "category": "下装",
                    "sub_category": "短裤",
                    "colors": ["白色"],
                    "style": [],
                }
            ]
        },
    ],
}


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLlm:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return FakeResponse(json.dumps(self.payload, ensure_ascii=False))


class SequenceLlm:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class OutfitAdviceServiceTest(unittest.TestCase):
    def test_将内部评分转换为固定五字段建议且不返回技术字段(self):
        from src.outfit_advice_service import OutfitAdviceService

        expected = {
            "verdict": "整体协调，可以尝试",
            "summary": "上衣和下装品类互补，配色较清爽。",
            "strengths": ["品类组合完整", "蓝白配色清爽"],
            "issues": ["风格信息有限"],
            "suggestions": ["可补充简洁鞋履保持休闲感"],
        }
        llm = FakeLlm(expected)

        result = OutfitAdviceService(llm).generate(ANALYSIS)

        self.assertEqual(result, expected)
        self.assertIn('"score": 70', llm.prompts[0])
        self.assertNotIn("shared_outfit_ids", llm.prompts[0])
        self.assertNotIn("graph_evidence", result)
        self.assertNotIn("rule_scores", result)

    def test_非法_JSON_只修复一次并返回修复后的_LLM_结果(self):
        from src.outfit_advice_service import OutfitAdviceService

        repaired = {
            "verdict": "可以尝试",
            "summary": "搭配方向基本协调。",
            "strengths": [],
            "issues": [],
            "suggestions": ["保持当前配色"],
        }
        llm = SequenceLlm(
            [
                "不是 JSON",
                json.dumps(repaired, ensure_ascii=False),
            ]
        )

        with self.assertLogs(
            "shopping_qna.performance",
            level="INFO",
        ) as logs:
            result = OutfitAdviceService(llm).generate(ANALYSIS)

        self.assertEqual(result, repaired)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("只修复 JSON 格式", llm.prompts[1])
        diagnostic = json.loads(logs.output[-1].split(":", 2)[-1])
        self.assertTrue(diagnostic["llm_success"])
        self.assertTrue(diagnostic["llm_parse_failed"])
        self.assertTrue(diagnostic["llm_parse_repair_used"])
        self.assertFalse(diagnostic["fallback_used"])
        self.assertEqual(diagnostic["llm_attempt_count"], 2)
        self.assertEqual(diagnostic["llm_retry_count"], 1)

    def test_JSON_修复仍失败时返回固定五字段_fallback(self):
        from src.outfit_advice_service import OutfitAdviceService

        llm = SequenceLlm(["坏 JSON", "仍然不是 JSON"])

        with self.assertLogs(
            "shopping_qna.performance",
            level="INFO",
        ) as logs:
            result = OutfitAdviceService(llm).generate(ANALYSIS)

        self.assertEqual(
            set(result),
            {"verdict", "summary", "strengths", "issues", "suggestions"},
        )
        self.assertNotIn("item_id", json.dumps(result, ensure_ascii=False))
        self.assertNotIn(
            "shared_outfit_ids",
            json.dumps(result, ensure_ascii=False),
        )
        diagnostic = json.loads(logs.output[-1].split(":", 2)[-1])
        self.assertTrue(diagnostic["fallback_used"])
        self.assertEqual(diagnostic["llm_attempt_count"], 2)
        self.assertEqual(diagnostic["error_type"], "JSONDecodeError")

    def test_网络超时时直接返回_fallback_且不抛错(self):
        from src.outfit_advice_service import OutfitAdviceService

        llm = SequenceLlm([TimeoutError("不应泄露的正文")])

        with self.assertLogs(
            "shopping_qna.performance",
            level="INFO",
        ) as logs:
            result = OutfitAdviceService(llm).generate(ANALYSIS)

        self.assertEqual(len(llm.prompts), 1)
        self.assertEqual(len(result), 5)
        diagnostic = json.loads(logs.output[-1].split(":", 2)[-1])
        self.assertTrue(diagnostic["fallback_used"])
        self.assertEqual(diagnostic["error_type"], "TimeoutError")
        self.assertNotIn("不应泄露的正文", "\n".join(logs.output))


@pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_SMOKE") != "1",
    reason="仅在 RUN_DASHSCOPE_SMOKE=1 时调用真实文本 LLM",
)
def test_真实文本_llm_返回五字段建议():
    from src.outfit_advice_service import build_outfit_advice_service

    result = build_outfit_advice_service().generate(ANALYSIS)

    assert set(result) == {
        "verdict",
        "summary",
        "strengths",
        "issues",
        "suggestions",
    }


if __name__ == "__main__":
    unittest.main()
