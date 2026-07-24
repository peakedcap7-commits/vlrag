import importlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from PIL import Image


MODEL_NAME = "OFA-Sys/chinese-clip-vit-base-patch16"
COLLECTION_NAME = "products_image_cnclip_v1"


class FakeVector:
    def __init__(self):
        self.values = [0.25] * 512

    def to(self, _device):
        return self

    def cpu(self):
        return self

    def detach(self):
        return self

    def numpy(self):
        return self

    def flatten(self):
        return self

    def squeeze(self, _dimension=None):
        return self

    def norm(self, **_kwargs):
        return 1.0

    def __getitem__(self, _index):
        return self

    def __itruediv__(self, _other):
        return self

    def __truediv__(self, _other):
        return self

    def tolist(self):
        return self.values


class FakeChineseCLIPModel:
    @classmethod
    def from_pretrained(cls, _model_name):
        return cls()

    def to(self, _device):
        return self

    def eval(self):
        return self

    def get_text_features(self, **_inputs):
        return FakeVector()

    def get_image_features(self, **_inputs):
        return FakeVector()

    def __call__(self, **_inputs):
        return types.SimpleNamespace(
            text_embeds=FakeVector(),
            image_embeds=FakeVector(),
        )


class FakeChineseCLIPProcessor:
    @classmethod
    def from_pretrained(cls, _model_name):
        return cls()

    def __call__(self, **_kwargs):
        return {}


class NoGrad:
    def __enter__(self):
        return None

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False


def import_chinese_clip_with_fake_dependencies():
    """使用假依赖导入适配器，避免安装模型运行时。"""
    transformers = types.ModuleType("transformers")
    transformers.ChineseCLIPModel = FakeChineseCLIPModel
    transformers.ChineseCLIPProcessor = FakeChineseCLIPProcessor
    torch = types.ModuleType("torch")
    torch.no_grad = NoGrad
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    functional = types.ModuleType("torch.nn.functional")
    functional.normalize = lambda value, **_kwargs: value
    nn = types.ModuleType("torch.nn")
    nn.functional = functional
    sys.modules.pop("src.config", None)
    sys.modules.pop("src.embeddings.chinese_clip", None)
    with patch.dict(os.environ, {"CHINESE_CLIP_MODEL": MODEL_NAME}), patch.dict(
        sys.modules,
        {
            "transformers": transformers,
            "torch": torch,
            "torch.nn": nn,
            "torch.nn.functional": functional,
        },
    ):
        return importlib.import_module("src.embeddings.chinese_clip")


def minimal_jpeg_bytes():
    """生成不依赖真实数据的最小 JPEG。"""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


class ChineseCLIPEmbeddingsTest(unittest.TestCase):
    def test_模型名支持环境变量配置(self):
        import src.config as config

        with patch.dict(
            os.environ,
            {"CHINESE_CLIP_MODEL": "本地/chinese-clip"},
        ):
            config = importlib.reload(config)
            self.assertEqual(config.CHINESE_CLIP_MODEL, "本地/chinese-clip")
        importlib.reload(config)

    def test_transformers_固定为已验证版本(self):
        project_root = Path(__file__).resolve().parents[1]
        pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"transformers==4.50.3"', pyproject)

    def test_导出模型名和向量维度(self):
        chinese_clip = import_chinese_clip_with_fake_dependencies()

        self.assertEqual(chinese_clip.MODEL_NAME, MODEL_NAME)
        self.assertEqual(chinese_clip.EMBEDDING_DIM, 512)

    def test_文本和图片输入均返回512维向量(self):
        chinese_clip = import_chinese_clip_with_fake_dependencies()
        embeddings = chinese_clip.ChineseCLIPEmbeddings()

        self.assertEqual(len(embeddings.embed_query("蓝色连衣裙")), 512)
        image_bytes = minimal_jpeg_bytes()
        self.assertEqual(len(embeddings.embed_image(image_bytes)), 512)
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "item.jpg"
            image_path.write_bytes(image_bytes)
            self.assertEqual(len(embeddings.embed_image(image_path)), 512)


class ChineseCLIPImageStoreTest(unittest.TestCase):
    def test_显式图片向量写入独立_collection(self):
        from src.vectordb.chinese_clip_image_store import (
            COLLECTION_NAME as actual_collection_name,
            upsert_image_embeddings,
        )

        items = [
            {
                "item_id": str(index),
                "bucket": "shopping-qna",
                "object_key": f"polyvore/items/{index}.jpg",
                "retrieval_text": f"第{index}件蓝色商品",
            }
            for index in range(1, 6)
        ]
        vectors = [[float(index)] * 512 for index in range(5)]
        collection = MagicMock()
        chroma_client = MagicMock()
        chroma_client.get_or_create_collection.return_value = collection

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            upsert_image_embeddings(
                items=items,
                embeddings=vectors,
                persist_dir=temp_path / "chroma",
                chroma_client=chroma_client,
            )

        self.assertEqual(actual_collection_name, COLLECTION_NAME)
        collection_call = chroma_client.get_or_create_collection.call_args
        called_name = collection_call.kwargs.get("name") or collection_call.args[0]
        self.assertEqual(called_name, COLLECTION_NAME)
        upsert = collection.upsert.call_args.kwargs
        self.assertEqual(upsert["ids"], [item["item_id"] for item in items])
        self.assertEqual(upsert["embeddings"], vectors)
        self.assertEqual(
            upsert["documents"],
            [item["retrieval_text"] for item in items],
        )
        for metadata, item in zip(upsert["metadatas"], items):
            self.assertEqual(
                metadata,
                {
                    "item_id": item["item_id"],
                    "bucket": item["bucket"],
                    "object_key": item["object_key"],
                    "retrieval_text": item["retrieval_text"],
                },
            )

    def test_store_不依赖_minio_json_或_openclip(self):
        project_root = Path(__file__).resolve().parents[1]
        new_store_source = (
            project_root / "src/vectordb/chinese_clip_image_store.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("minio", new_store_source.lower())
        self.assertNotIn("import json", new_store_source)
        self.assertNotIn("src.embeddings.openclip", new_store_source)

    def test_图片主_collection_已切换(self):
        project_root = Path(__file__).resolve().parents[1]
        image_store_source = (project_root / "src/vectordb/image_store.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'COLLECTION_NAME = "products_image_cnclip_v1"',
            image_store_source,
        )


class ChineseCLIPIndexCliTest(unittest.TestCase):
    def test_入口编排前五条_minio_图片并调用_store(self):
        fake_store = types.ModuleType("src.vectordb.chinese_clip_image_store")
        fake_store.COLLECTION_NAME = COLLECTION_NAME
        fake_store.upsert_image_embeddings = MagicMock(
            return_value={"ingested": 5, "collection": COLLECTION_NAME}
        )
        fake_embeddings_module = types.ModuleType("src.embeddings.chinese_clip")
        fake_embeddings_module.ChineseCLIPEmbeddings = MagicMock
        sys.modules.pop("tools.cli_cnclip_index", None)
        with patch.dict(
            sys.modules,
            {
                "src.vectordb.chinese_clip_image_store": fake_store,
                "src.embeddings.chinese_clip": fake_embeddings_module,
            },
        ):
            cli_module = importlib.import_module("tools.cli_cnclip_index")

        records = [
            {
                "item_id": str(index),
                "bucket": "shopping-qna",
                "object_key": f"polyvore/items/{index}.jpg",
                "retrieval_text": f"第{index}件蓝色商品",
            }
            for index in range(1, 7)
        ]
        responses = []
        for _record in records[:5]:
            response = MagicMock()
            response.read.return_value = minimal_jpeg_bytes()
            responses.append(response)
        minio_client = MagicMock()
        minio_client.get_object.side_effect = responses
        embeddings = MagicMock()
        vectors = [[float(index)] * 512 for index in range(5)]
        embeddings.embed_image.side_effect = vectors
        chroma_client = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            enriched_path = temp_path / "enriched.jsonl"
            enriched_path.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            cli_module.ingest_enriched_sample(
                enriched_path=enriched_path,
                persist_dir=temp_path / "chroma",
                limit=5,
                minio_client=minio_client,
                embeddings=embeddings,
                chroma_client=chroma_client,
            )

        self.assertEqual(
            minio_client.get_object.call_args_list,
            [
                call(record["bucket"], record["object_key"])
                for record in records[:5]
            ],
        )
        self.assertEqual(embeddings.embed_image.call_count, 5)
        store_call = fake_store.upsert_image_embeddings.call_args.kwargs
        self.assertEqual(store_call["items"], records[:5])
        self.assertEqual(store_call["embeddings"], vectors)
        self.assertEqual(store_call["chroma_client"], chroma_client)


if __name__ == "__main__":
    unittest.main()
