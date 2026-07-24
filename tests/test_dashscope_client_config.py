import unittest
from unittest.mock import patch


class DashScopeClientConfigTest(unittest.TestCase):
    def test_build_chat_llm_透传显式超时与重试(self):
        from src.llm.dashscope_client import build_chat_llm

        with patch(
            "src.llm.dashscope_client.ChatOpenAI"
        ) as chat_openai:
            build_chat_llm(
                model="qwen-turbo",
                temperature=0.2,
                timeout=12,
                max_retries=1,
            )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 12)
        self.assertEqual(kwargs["max_retries"], 1)

    def test_M2_M3_advice_builder_固定使用_12秒和一次重试(self):
        from src.outfit_advice_service import build_outfit_advice_service
        from src.outfit_revise_advice_service import (
            build_outfit_revise_advice_service,
        )

        with patch(
            "src.llm.dashscope_client.build_chat_llm"
        ) as build_chat_llm:
            build_outfit_advice_service()
            build_outfit_revise_advice_service()

        self.assertEqual(build_chat_llm.call_count, 2)
        for call in build_chat_llm.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 12)
            self.assertEqual(call.kwargs["max_retries"], 1)


if __name__ == "__main__":
    unittest.main()
