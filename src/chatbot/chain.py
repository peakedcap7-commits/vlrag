"""RAG Chatbot 主链 —— 检索 + 生成"""
from typing import List, Literal

from langchain_chroma import Chroma

from src.config import QWEN_MAX
from src.llm.dashscope_client import build_chat_llm
from src.retrievers.base import BaseRetriever
from src.chatbot.prompts import SYSTEM_PROMPT, CHAT_PROMPT
from src.chatbot.history import ConversationManager

RetrieverType = Literal["multimodal", "text", "hybrid"]


class ShoppingChatbot:
    """
    Shopping QnA Chatbot。
    支持三种检索模式切换 + 多轮对话 + 文本/图片查询。

    检索器懒加载：只实例化当前模式的检索器，
    避免一次加载全部（尤其是 Chinese-CLIP 只在使用 hybrid/multimodal 时才加载）。
    """

    def __init__(
        self,
        text_db: Chroma,
        products: List[dict],
        image_db: Chroma | None = None,
    ):
        self._image_db = image_db
        self._text_db = text_db
        self.products = products

        self._retriever: BaseRetriever | None = None
        self._retriever_type = "text"  # 默认纯文本，不加载 Chinese-CLIP
        self._llm = build_chat_llm(model=QWEN_MAX, temperature=0.7)
        self._conversation = ConversationManager()

    @property
    def retriever(self) -> BaseRetriever:
        """懒加载当前配置的检索器"""
        if self._retriever is None:
            self._retriever = self._build_retriever(self._retriever_type)
        return self._retriever

    def _ensure_image_db(self):
        """延迟加载 image_db，仅 multimodal/hybrid 模式触发"""
        if self._image_db is None:
            from src.vectordb.image_store import load_image_store
            self._image_db = load_image_store()
            print("Chinese-CLIP 图片向量库已加载")

    def _build_retriever(self, rtype: RetrieverType) -> BaseRetriever:
        if rtype == "multimodal":
            self._ensure_image_db()
            from src.retrievers.multimodal import MultimodalRetriever
            return MultimodalRetriever(self._image_db, self.products)
        if rtype == "text":
            from src.retrievers.text_embedding import TextEmbeddingRetriever
            return TextEmbeddingRetriever(self._text_db, self.products)
        if rtype == "hybrid":
            self._ensure_image_db()
            from src.retrievers.hybrid import HybridRetriever
            return HybridRetriever(self._image_db, self._text_db, self.products)
        raise ValueError(f"未知检索器类型: {rtype}")

    def switch_retriever(self, retriever_type: RetrieverType):
        """切换检索器模式"""
        if retriever_type != self._retriever_type:
            self._retriever = None
            self._retriever_type = retriever_type
            print(f"检索器已切换为: {retriever_type}")

    def chat(self, query: str, img_b64: str = "") -> str:
        """
        对话入口，按输入自动选择检索器：
        - 纯文本     → text 检索器（v3 原生中文，不加载 Chinese-CLIP）
        - 上传图片   → multimodal 检索器（CLIP 图片编码）
        - 图文都有   → hybrid 检索器（双路 RRF 融合）
        """
        if img_b64:
            rtype: RetrieverType = "hybrid" if query else "multimodal"
        else:
            rtype = "text"

        self.switch_retriever(rtype)
        items = self.retriever.retrieve(query=query, is_image=bool(img_b64), img_b64=img_b64)

        # 构建上下文
        context = "\n\n".join(item.to_context() for item in items)
        history = self._conversation.get_history_text()

        # 4. 生成回答
        prompt = CHAT_PROMPT.format(
            system=SYSTEM_PROMPT,
            history=history if history else "（新对话）",
            question=query,
            context=context,
        )

        response = self._llm.invoke(prompt).content.strip()

        # 5. 更新对话历史
        self._conversation.add_user_message(query)
        self._conversation.add_ai_message(response)

        return response

    def clear_history(self):
        """清空对话历史"""
        self._conversation.clear()
