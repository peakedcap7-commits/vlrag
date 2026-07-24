"""百炼 API 连通性测试"""
import os

import pytest

from src.config import DASHSCOPE_API_KEY, QWEN_TURBO
from src.llm.dashscope_client import build_chat_llm


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DASHSCOPE_SMOKE") != "1",
    reason="仅在 RUN_DASHSCOPE_SMOKE=1 时调用真实百炼服务",
)


def test_api_key_exists():
    """验证 API Key 已配置"""
    assert DASHSCOPE_API_KEY is not None
    assert DASHSCOPE_API_KEY != "sk-xxx"
    assert DASHSCOPE_API_KEY.startswith("sk-")


def test_qwen_turbo_ping():
    """验证 qwen-turbo 连通性 —— 一次简单对话"""
    llm = build_chat_llm(model=QWEN_TURBO)
    resp = llm.invoke("hi")
    assert resp.content is not None
    assert len(resp.content) > 0


def test_qwen_max_ping():
    """验证 qwen-max 连通性"""
    llm = build_chat_llm()
    resp = llm.invoke("你好，1+1等于几？")
    assert "2" in resp.content
