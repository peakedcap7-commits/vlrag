"""检索器测试"""
import pytest

from src.retrievers.models import ItemWrapper, fetch_products
from src.retrievers.multimodal import MultimodalRetriever
from src.retrievers.text_embedding import TextEmbeddingRetriever
from src.retrievers.hybrid import HybridRetriever


# 模拟商品数据
MOCK_PRODUCTS = [
    {
        "name": "黑色机车夹克",
        "type": "夹克",
        "description": "经典机车风格真皮夹克",
        "image_summary": "黑色真皮，银色拉链",
        "summary": "黑色夹克",
        "tags": ["黑色", "真皮", "机车风", "秋冬"],
        "image_path": "data/raw/images/product_0.jpg",
    },
    {
        "name": "蓝色牛仔裤",
        "type": "裤子",
        "description": "修身直筒牛仔裤",
        "image_summary": "蓝色水洗，直筒版型",
        "summary": "蓝色牛仔裤",
        "tags": ["蓝色", "牛仔", "休闲", "四季"],
        "image_path": "data/raw/images/product_1.jpg",
    },
    {
        "name": "白色运动鞋",
        "type": "鞋子",
        "description": "轻便透气跑步鞋",
        "image_summary": "白色网面，橡胶底",
        "summary": "白色运动鞋",
        "tags": ["白色", "运动", "透气", "春夏"],
        "image_path": "data/raw/images/product_2.jpg",
    },
]


class TestItemWrapper:
    def test_to_context(self):
        item = ItemWrapper(
            product_id=0,
            name="测试商品",
            type="测试类型",
            description="测试描述",
            tags=["标签1", "标签2"],
            score=0.85,
            source="hybrid",
        )
        ctx = item.to_context()
        assert "[0] 测试商品" in ctx
        assert "标签1, 标签2" in ctx


class TestFetchProducts:
    def test_fetch(self):
        items = fetch_products([0, 2], MOCK_PRODUCTS)
        assert len(items) == 2
        assert items[0].name == "黑色机车夹克"
        assert items[1].name == "白色运动鞋"

    def test_fetch_out_of_range(self):
        items = fetch_products([999], MOCK_PRODUCTS)
        assert len(items) == 0
