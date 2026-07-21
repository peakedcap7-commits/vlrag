"""检索器测试"""
import base64
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.retrievers.models import ItemWrapper, fetch_products


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


def import_multimodal_with_fake_dependencies():
    """使用假依赖导入检索器，避免加载向量库和真实模型。"""
    langchain_chroma = types.ModuleType("langchain_chroma")
    langchain_chroma.Chroma = object
    chinese_clip = types.ModuleType("src.embeddings.chinese_clip")
    chinese_clip.ChineseCLIPEmbeddings = FakeChineseCLIPEmbeddings
    sys.modules.pop("src.retrievers.multimodal", None)
    with patch.dict(
        sys.modules,
        {
            "langchain_chroma": langchain_chroma,
            "src.embeddings.chinese_clip": chinese_clip,
        },
    ):
        return importlib.import_module("src.retrievers.multimodal")


class FakeChineseCLIPEmbeddings:
    """记录编码输入，不执行真实模型推理。"""

    def __init__(self):
        self.image_inputs = []

    def embed_query(self, _query):
        return [0.1] * 512

    def embed_image(self, image_bytes):
        self.image_inputs.append(image_bytes)
        return [0.2] * 512


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

    def test_fetch_polyvore_enriched_fields(self):
        products = [
            {
                "item_id": "sku-42",
                "category": "服装",
                "sub_category": "连衣裙",
                "retrieval_text": "蓝色夏季连衣裙",
                "colors": ["蓝色"],
                "style": ["休闲"],
            }
        ]

        item = fetch_products(["sku-42"], products)[0]

        assert item.name == "蓝色夏季连衣裙"
        assert item.type == "连衣裙"
        assert item.description == "蓝色夏季连衣裙"
        assert item.tags == ["蓝色", "休闲"]


class TestMultimodalRetrieverChineseCLIP契约:
    def test_collection_item_id_映射到商品并返回包装对象(self):
        multimodal = import_multimodal_with_fake_dependencies()
        image_db = MagicMock()
        image_db.similarity_search_by_vector.return_value = [
            SimpleNamespace(metadata={"item_id": "sku-42", "distance": 0.25})
        ]
        products = [
            {
                "item_id": "sku-42",
                "name": "蓝色连衣裙",
                "type": "连衣裙",
                "description": "轻薄夏季连衣裙",
                "tags": ["蓝色", "夏季"],
            }
        ]
        retriever = multimodal.MultimodalRetriever(image_db, products)
        retriever._embeddings = FakeChineseCLIPEmbeddings()

        items = retriever.retrieve_by_text("蓝色连衣裙")

        assert len(items) == 1
        assert isinstance(items[0], ItemWrapper)
        assert items[0].product_id == "sku-42"
        assert items[0].name == "蓝色连衣裙"
        assert items[0].source == "multimodal"

    def test_图片查询解码_base64_后调用_embed_image(self):
        multimodal = import_multimodal_with_fake_dependencies()
        image_bytes = b"\xff\xd8\xff\xe0Chinese-CLIP"
        image_db = MagicMock()
        image_db.similarity_search_by_vector.return_value = []
        retriever = multimodal.MultimodalRetriever(image_db, [])

        items = retriever.retrieve_by_image(
            base64.b64encode(image_bytes).decode("ascii")
        )

        assert items == []
        assert isinstance(retriever.embeddings, FakeChineseCLIPEmbeddings)
        assert retriever.embeddings.image_inputs == [image_bytes]
        image_db.similarity_search_by_vector.assert_called_once_with(
            [0.2] * 512,
            k=retriever.k,
        )
