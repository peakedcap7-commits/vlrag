"""百炼 text-embedding-v3 的 OpenAI 兼容接口适配器。"""

from typing import List

import httpx
from openai import OpenAI

from src.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, TEXT_EMBEDDING_V3


class DashScopeEmbeddings:
    """提供项目现有检索链所需的文本嵌入接口。"""

    def __init__(
        self,
        model=TEXT_EMBEDDING_V3,
        dashscope_api_key=DASHSCOPE_API_KEY,
        client=None,
    ):
        self.model = model
        self.client = client or OpenAI(
            api_key=dashscope_api_key,
            base_url=DASHSCOPE_BASE_URL,
            http_client=httpx.Client(trust_env=False, timeout=60),
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量生成文本向量，并按输入索引稳定返回。"""
        if not texts:
            return []
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [
            item.embedding
            for item in sorted(response.data, key=lambda item: item.index)
        ]

    def embed_query(self, text: str) -> List[float]:
        """生成单条查询向量。"""
        return self.embed_documents([text])[0]
