"""图数据库检索器 —— 抽象基类 + 空实现（预留接口）"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from src.graph.relation_type import RelationType


@dataclass
class ProductNode:
    """图数据库中的商品节点"""
    product_id: str
    name: str
    score: float
    relation: RelationType
    source: str  # "amazon" | "dewu" | "smzdm" | "llm"


class GraphRetriever(ABC):
    """图检索器抽象基类。后续接入 Neo4j 时实现此类即可。"""

    @abstractmethod
    def retrieve_by_product(
        self,
        product_ids: List[str],
        relations: Optional[List[RelationType]] = None,
        top_k: int = 5,
    ) -> List[ProductNode]:
        """根据商品 ID 查找关联商品"""

    @abstractmethod
    def retrieve_by_category(self, category: str, top_k: int = 5) -> List[ProductNode]:
        """根据品类查找商品"""

    @abstractmethod
    def retrieve_by_style(self, style: str, top_k: int = 5) -> List[ProductNode]:
        """根据风格查找商品"""


class DummyGraphRetriever(GraphRetriever):
    """空实现 —— 一期占位，所有方法返回空列表"""

    def retrieve_by_product(self, *args, **kwargs) -> List[ProductNode]:
        return []

    def retrieve_by_category(self, *args, **kwargs) -> List[ProductNode]:
        return []

    def retrieve_by_style(self, *args, **kwargs) -> List[ProductNode]:
        return []
