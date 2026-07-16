"""Text Embedding Retriever —— 基于百炼 text-embedding-v3 的文本检索"""
from typing import List

from langchain_chroma import Chroma

from src.config import RETRIEVER_K
from src.llm.dashscope_client import describe_image_b64
from src.retrievers.base import BaseRetriever
from src.retrievers.models import ItemWrapper, fetch_products


class TextEmbeddingRetriever(BaseRetriever):
    """
    文本嵌入检索器：
    - 文本查询：直接 text-embedding-v3 编码 → text_db
    - 图片查询：qwen-vl-max 描述图片 → text-embedding-v3 编码 → text_db
    """

    def __init__(self, text_db: Chroma, products: List[dict], k: int = RETRIEVER_K):
        self.text_db = text_db
        self.products = products
        self.k = k

    def retrieve_by_text(self, query: str) -> List[ItemWrapper]:
        """文本查询，直接向量检索"""
        docs = self.text_db.similarity_search(query, k=self.k)
        return self._build_items(docs, "text")

    def retrieve_by_image(self, img_b64: str) -> List[ItemWrapper]:
        """图片查询：先 qwen-vl-max 描述，再向量检索"""
        description = describe_image_b64(img_b64)
        docs = self.text_db.similarity_search(description, k=self.k)
        return self._build_items(docs, "text")

    def retrieve(self, query: str = "", is_image: bool = False, img_b64: str = "") -> List[ItemWrapper]:
        if is_image and img_b64:
            return self.retrieve_by_image(img_b64)
        return self.retrieve_by_text(query)

    def _build_items(self, docs, source: str) -> List[ItemWrapper]:
        """Document 列表 → ItemWrapper 列表"""
        product_ids = [doc.metadata["product_id"] for doc in docs]
        items = fetch_products(product_ids, self.products)
        for item in items:
            item.score = 1.0  # Chroma similarity_search 不返回分数
            item.source = source
        return items
