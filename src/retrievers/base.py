"""检索器抽象基类 —— 统一三种检索器的接口"""
from abc import ABC, abstractmethod
from typing import List

from src.retrievers.models import ItemWrapper


class BaseRetriever(ABC):
    """检索器统一接口。所有检索器必须实现 retrieve 方法。"""

    @abstractmethod
    def retrieve(
        self,
        query: str = "",
        is_image: bool = False,
        img_b64: str = "",
    ) -> List[ItemWrapper]:
        """
        统一检索入口。
        - query: 用户文本查询
        - is_image: 是否图片查询
        - img_b64: 图片查询时的 base64 编码
        返回 ItemWrapper 列表，按相关度降序排列。
        """
        ...
