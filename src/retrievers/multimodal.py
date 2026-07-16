"""Multimodal Retriever —— 基于 OpenCLIP 的图文检索"""
from typing import List

from langchain_chroma import Chroma

from src.config import RETRIEVER_K
from src.embeddings.openclip import OpenCLIPEmbeddings
from src.retrievers.base import BaseRetriever
from src.retrievers.models import ItemWrapper, fetch_products


class MultimodalRetriever(BaseRetriever):
    """
    多模态检索器：
    - 图片查询：base64 → OpenCLIP 图片编码器 → image_db
    - 文本查询：中文 → qwen-turbo 翻译 → OpenCLIP 文本编码器 → image_db
    """

    def __init__(self, image_db: Chroma, products: List[dict], k: int = RETRIEVER_K):
        self.image_db = image_db
        self.products = products
        self.k = k
        self._embeddings: OpenCLIPEmbeddings | None = None

    @property
    def embeddings(self) -> OpenCLIPEmbeddings:
        if self._embeddings is None:
            self._embeddings = OpenCLIPEmbeddings()
        return self._embeddings

    def retrieve_by_text(self, query: str) -> List[ItemWrapper]:
        """文本查询 → CLIP 文本编码器检索"""
        # 中文翻译在 embed_query 内部处理
        vector = self.embeddings.embed_query(query)
        docs = self.image_db.similarity_search_by_vector(vector, k=self.k)

        product_ids = [doc.metadata["product_id"] for doc in docs]
        items = fetch_products(product_ids, self.products)
        for item, doc in zip(items, docs):
            item.score = 1.0 - float(doc.metadata.get("distance", 0.0))  # 近似
            item.source = "multimodal"
        return items

    def retrieve_by_image(self, img_b64: str) -> List[ItemWrapper]:
        """图片查询 → CLIP 图片编码器检索"""
        vector = self.embeddings.embed_image_from_base64(img_b64)
        docs = self.image_db.similarity_search_by_vector(vector, k=self.k)

        product_ids = [doc.metadata["product_id"] for doc in docs]
        items = fetch_products(product_ids, self.products)
        for item, doc in zip(items, docs):
            item.score = 1.0 - float(doc.metadata.get("distance", 0.0))
            item.source = "multimodal"
        return items

    def retrieve(self, query: str, is_image: bool = False, img_b64: str = "") -> List[ItemWrapper]:
        """统一检索入口"""
        if is_image and img_b64:
            return self.retrieve_by_image(img_b64)
        return self.retrieve_by_text(query)
