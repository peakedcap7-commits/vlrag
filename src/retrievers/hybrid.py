"""Hybrid Retriever —— 双路并行检索 + RRF 融合"""
from typing import List

from langchain_chroma import Chroma

from src.config import RETRIEVER_K, RERANK_TOP_K
from src.retrievers.base import BaseRetriever
from src.retrievers.models import ItemWrapper

# RRF 常数，取值越大排名靠后的贡献越小，业界默认 60
RRF_K = 60


class HybridRetriever(BaseRetriever):
    """
    混合检索器：
    1. 双路并行检索：图片路（OpenCLIP）+ 文本路（text-embedding-v3）
    2. RRF（Reciprocal Rank Fusion）融合排序，零 API 成本
    3. 取 Top-K 返回

    子检索器懒加载，避免不使用 Hybrid 时加载 OpenCLIP。
    """

    def __init__(
        self,
        image_db: Chroma,
        text_db: Chroma,
        products: List[dict],
        k: int = RETRIEVER_K,
        rerank_k: int = RERANK_TOP_K,
    ):
        self._image_db = image_db
        self._text_db = text_db
        self.products = products
        self.k = k
        self.rerank_k = rerank_k
        self._multimodal = None
        self._text_retriever = None

    @property
    def multimodal(self):
        if self._multimodal is None:
            from src.retrievers.multimodal import MultimodalRetriever
            self._multimodal = MultimodalRetriever(self._image_db, self.products, k=self.k)
        return self._multimodal

    @property
    def text_retriever(self):
        if self._text_retriever is None:
            from src.retrievers.text_embedding import TextEmbeddingRetriever
            self._text_retriever = TextEmbeddingRetriever(self._text_db, self.products, k=self.k)
        return self._text_retriever

    def retrieve_by_text(self, query: str) -> List[ItemWrapper]:
        multimodal_items = self.multimodal.retrieve_by_text(query)
        text_items = self.text_retriever.retrieve_by_text(query)
        return self._rrf_fuse(multimodal_items, text_items)[: self.rerank_k]

    def retrieve_by_image(self, img_b64: str, query: str = "") -> List[ItemWrapper]:
        multimodal_items = self.multimodal.retrieve_by_image(img_b64)
        text_items = self.text_retriever.retrieve_by_image(img_b64)
        return self._rrf_fuse(multimodal_items, text_items)[: self.rerank_k]

    def retrieve(
        self,
        query: str = "",
        is_image: bool = False,
        img_b64: str = "",
    ) -> List[ItemWrapper]:
        if is_image and img_b64:
            return self.retrieve_by_image(img_b64, query)
        return self.retrieve_by_text(query)

    def _rrf_fuse(
        self,
        items_a: List[ItemWrapper],
        items_b: List[ItemWrapper],
    ) -> List[ItemWrapper]:
        """
        RRF 融合两条检索结果，零 API 成本。
        对每条结果按其在各路的排名计算 RRF 分数，合并后按分数降序排列。
        """
        rrf_scores: dict[int, float] = {}

        # 图片路 → RRF 分数累加
        for rank, item in enumerate(items_a, start=1):
            rrf_scores[item.product_id] = rrf_scores.get(item.product_id, 0) + 1 / (RRF_K + rank)

        # 文本路 → RRF 分数累加
        for rank, item in enumerate(items_b, start=1):
            rrf_scores[item.product_id] = rrf_scores.get(item.product_id, 0) + 1 / (RRF_K + rank)

        # 构建结果列表
        id_to_item: dict[int, ItemWrapper] = {}
        for item in items_a + items_b:
            if item.product_id not in id_to_item:
                item.source = "hybrid"
                id_to_item[item.product_id] = item

        for pid, item in id_to_item.items():
            item.score = rrf_scores.get(pid, 0)

        return sorted(id_to_item.values(), key=lambda x: x.score, reverse=True)
