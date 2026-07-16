"""百炼 text-embedding-v3 适配 —— 基于 LangChain 社区集成"""
from typing import List

from langchain_community.embeddings import DashScopeEmbeddings as _DashScopeEmbeddings

from src.config import TEXT_EMBEDDING_V3, DASHSCOPE_API_KEY


class DashScopeEmbeddings(_DashScopeEmbeddings):
    """
    百炼文本嵌入封装。
    默认使用 text-embedding-v3，输出 1024 维向量。
    """

    def __init__(self, **kwargs):
        super().__init__(
            model=kwargs.pop("model", TEXT_EMBEDDING_V3),
            dashscope_api_key=kwargs.pop("dashscope_api_key", DASHSCOPE_API_KEY),
            **kwargs,
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量文本嵌入"""
        return super().embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        """单条查询嵌入"""
        return super().embed_query(text)
