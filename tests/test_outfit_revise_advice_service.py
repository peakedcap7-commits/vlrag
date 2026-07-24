import json
import os
import unittest

import pytest


REVISE_RESULT = {
    "exclude_categories": ["裙子"],
    "prefer_categories": ["裤子"],
    "keep_items": ["上衣"],
    "prefer_colors": ["蓝色"],
    "style_shift": "more_formal",
    "rewrite_scope": "partial",
    "bound_keep_item_ids": ["top-1"],
    "bound_exclude_item_ids": ["skirt-1"],
    "needs_clarification": False,
    "clarification_question": "",
    "confidence": 1.0,
    "replacement_candidates": [
        {
            "item_id": "pants-1",
            "object_key": "polyvore/items/pants-1.jpg",
            "category": "下装",
            "sub_category": "牛仔裤",
            "colors": ["蓝色"],
            "style": ["正式"],
            "match_level": "strong",
            "reason": "更适合作为当前搭配的替换单品。",
        }
    ],
}

CONVERSATION_STATE = {
    "anchor_item_id": "199614803",
    "locked_item_ids": ["199614803"],
    "item_metadata": [
        {
            "item_id": "199614803",
            "category": "上衣",
            "sub_category": "衬衫",
            "colors": ["蓝色"],
            "style": ["休闲"],
        },
        {
            "item_id": "211259367",
            "category": "下装",
            "sub_category": "半身裙",
            "colors": ["黑色"],
            "style": [],
        },
    ],
}


def assert_no_technical_identifier(test_case, value):
    serialized = json.dumps(value, ensure_ascii=False)
    for forbidden in (
        "199614803",
        "211259367",
        "item_id",
        "object_key",
        "outfit_id",
        "shared_outfit_ids",
        "graph_score",
        "rule_scores",
    ):
        test_case.assertNotIn(forbidden, serialized)


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


class OutfitReviseAdviceServiceTest(unittest.TestCase):
    def test_将排序后候选转换为固定四字段用户建议(self):
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        expected = {
            "verdict": "建议将裙子换成蓝色牛仔裤",
            "summary": "保留当前上衣，替换下装后更符合正式方向。",
            "changes": ["移除裙子", "换成蓝色牛仔裤"],
            "suggestions": ["优先尝试排在首位的强匹配候选"],
        }
        llm = FakeLlm(expected)

        result = OutfitReviseAdviceService(llm).generate(
            REVISE_RESULT,
            CONVERSATION_STATE,
        )

        self.assertEqual(result, expected)
        self.assertIn("当前蓝色衬衫", llm.prompts[0])
        self.assertNotIn("199614803", llm.prompts[0])
        self.assertNotIn("211259367", llm.prompts[0])
        self.assertNotIn("retained_item_ids", llm.prompts[0])
        assert_no_technical_identifier(self, result)
        self.assertIn('"match_level": "strong"', llm.prompts[0])
        self.assertIn('"reason": "更适合作为当前搭配的替换单品。"', llm.prompts[0])
        self.assertNotIn("shared_outfit_ids", llm.prompts[0])
        self.assertNotIn("graph_score", llm.prompts[0])
        self.assertNotIn("rule_scores", llm.prompts[0])
        self.assertIn("不得重新选择、删除、增加或调整候选顺序", llm.prompts[0])

    def test_没有保留项时不向模型传递空标识(self):
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        llm = FakeLlm(
            {
                "verdict": "建议替换",
                "summary": "按当前方向调整。",
                "changes": [],
                "suggestions": [],
            }
        )

        OutfitReviseAdviceService(llm).generate(REVISE_RESULT, {})

        self.assertNotIn("null", llm.prompts[0])

    def test_模型持续返回额外技术字段时使用安全_fallback(self):
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        invalid = json.dumps(
            {
                "verdict": "建议替换",
                "summary": "符合方向。",
                "changes": [],
                "suggestions": [],
                "shared_outfit_ids": ["outfit-1"],
            },
            ensure_ascii=False,
        )
        llm = SequenceLlm([invalid, invalid])

        result = OutfitReviseAdviceService(llm).generate(REVISE_RESULT, {})

        self.assertEqual(
            set(result),
            {"verdict", "summary", "changes", "suggestions"},
        )
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("shared_outfit_ids", serialized)
        self.assertNotIn("graph_score", serialized)
        self.assertNotIn("item_id", serialized)

    def test_非法_JSON_修复成功并记录诊断(self):
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        repaired = {
            "verdict": "建议替换",
            "summary": "保留物品 199614803，裤装更符合当前方向。",
            "changes": ["更换下装"],
            "suggestions": ["不要输出 item_id 或 object_key"],
        }
        llm = SequenceLlm(
            ["无法解析", json.dumps(repaired, ensure_ascii=False)]
        )

        with self.assertLogs(
            "shopping_qna.performance",
            level="INFO",
        ) as logs:
            result = OutfitReviseAdviceService(llm).generate(
                REVISE_RESULT,
                CONVERSATION_STATE,
            )

        assert_no_technical_identifier(self, result)
        self.assertIn("当前蓝色衬衫", result["summary"])
        self.assertIn("不得输出商品 ID", llm.prompts[1])
        diagnostic = json.loads(logs.output[-1].split(":", 2)[-1])
        self.assertTrue(diagnostic["llm_parse_repair_used"])
        self.assertFalse(diagnostic["fallback_used"])

    def test_SSL_错误返回四字段_fallback(self):
        from src.outfit_revise_advice_service import (
            OutfitReviseAdviceService,
        )

        llm = SequenceLlm([ConnectionError("SSL EOF 敏感正文")])

        with self.assertLogs(
            "shopping_qna.performance",
            level="INFO",
        ) as logs:
            result = OutfitReviseAdviceService(llm).generate(
                REVISE_RESULT,
                CONVERSATION_STATE,
            )

        self.assertEqual(len(result), 4)
        assert_no_technical_identifier(self, result)
        self.assertIn("当前蓝色衬衫", result["summary"])
        diagnostic = json.loads(logs.output[-1].split(":", 2)[-1])
        self.assertTrue(diagnostic["fallback_used"])
        self.assertEqual(diagnostic["error_type"], "ConnectionError")
        self.assertNotIn("敏感正文", "\n".join(logs.output))


@pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_SMOKE") != "1",
    reason="仅在 RUN_DASHSCOPE_SMOKE=1 时调用真实文本 LLM",
)
def test_真实文本_llm_返回四字段改搭建议():
    from src.outfit_revise_advice_service import (
        build_outfit_revise_advice_service,
    )

    result = build_outfit_revise_advice_service().generate(
        REVISE_RESULT,
        {"anchor_item_id": "top-1", "locked_item_ids": ["top-1"]},
    )

    assert set(result) == {
        "verdict",
        "summary",
        "changes",
        "suggestions",
    }


if __name__ == "__main__":
    unittest.main()
