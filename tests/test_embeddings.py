"""嵌入模型测试"""
import pytest

from src.config import TEXT_EMBEDDING_V3
from src.embeddings.dashscope_emb import DashScopeEmbeddings
from src.embeddings.openclip import OpenCLIPEmbeddings


class TestDashScopeEmbeddings:
    """百炼 text-embedding-v3 测试"""

    def test_embed_query_dimension(self):
        """验证输出维度为 1024"""
        emb = DashScopeEmbeddings()
        vector = emb.embed_query("黑色真皮机车夹克")
        assert len(vector) == 1024

    def test_embed_documents_batch(self):
        """验证批量嵌入"""
        emb = DashScopeEmbeddings()
        texts = ["红色连衣裙", "蓝色牛仔裤", "白色运动鞋"]
        vectors = emb.embed_documents(texts)
        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)


class TestOpenCLIPEmbeddings:
    """OpenCLIP 嵌入测试"""

    @pytest.fixture(scope="class")
    def clip_emb(self):
        return OpenCLIPEmbeddings()

    def test_embed_query_dimension(self, clip_emb):
        """验证输出维度为 512"""
        vector = clip_emb.embed_query("black leather jacket")
        assert len(vector) == 512

    def test_embed_chinese_text(self, clip_emb):
        """验证中文文本嵌入（含翻译回退）"""
        vector = clip_emb.embed_query("黑色皮夹克")
        assert len(vector) == 512
