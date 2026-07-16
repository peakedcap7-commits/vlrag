"""检索回调 —— 结果可视化 & 日志"""
import logging
from typing import List

from langchain.callbacks.base import BaseCallbackHandler

from src.retrievers.models import ItemWrapper

logger = logging.getLogger(__name__)


class LoggingCallbackHandler(BaseCallbackHandler):
    """检索过程日志回调"""

    def on_retriever_start(self, serialized: dict, query: str, **kwargs):
        logger.info(f"[检索开始] query={query[:80]}...")

    def on_retriever_end(self, documents: list, **kwargs):
        logger.info(f"[检索结束] 返回 {len(documents)} 条结果")


def print_results(items: List[ItemWrapper], title: str = "检索结果"):
    """格式化打印检索结果"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    for item in items:
        print(f"  [{item.product_id}] {item.name}")
        print(f"  类型: {item.type}")
        print(f"  描述: {item.description[:60]}...")
        print(f"  标签: {', '.join(item.tags)}")
        print(f"  来源: {item.source} | 分数: {item.score:.4f}")
        print()
