import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

from PIL import Image


EXPECTED_VLM_FIELDS = {
    "item_id",
    "category",
    "sub_category",
    "colors",
    "material",
    "style",
    "details",
    "scene",
    "retrieval_text",
    "confidence",
    "uncertain_fields",
}


def valid_vlm_result():
    """构造符合提示词约定的十一字段结果。"""
    return {
        "item_id": "175787103",
        "category": "连衣裙",
        "sub_category": "日常连衣裙",
        "colors": ["蓝色"],
        "material": "",
        "style": ["休闲"],
        "details": ["短袖"],
        "scene": ["日常"],
        "retrieval_text": "蓝色休闲短袖连衣裙，适合日常穿着",
        "confidence": 0.9,
        "uncertain_fields": ["material"],
    }


def minimal_jpeg_bytes():
    """生成 runner 测试使用的最小 JPEG。"""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


class PolyvoreVlmResultValidationTest(unittest.TestCase):
    def test_合法十一字段且中文检索文本通过(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        self.assertEqual(_validate_vlm_result(result), result)

    def test_缺少字段被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        result.pop("scene")
        with self.assertRaises(ValueError):
            _validate_vlm_result(result)

    def test_错误类型被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        result["colors"] = "蓝色"
        with self.assertRaises(ValueError):
            _validate_vlm_result(result)

    def test_额外字段被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        result["brand"] = "模型编造品牌"
        with self.assertRaises(ValueError):
            _validate_vlm_result(result)

    def test_非中文检索文本被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        result["retrieval_text"] = "blue casual dress"
        with self.assertRaises(ValueError):
            _validate_vlm_result(result)

    def test_非空材质被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        result["material"] = "棉质"
        with self.assertRaises(ValueError):
            _validate_vlm_result(result)

    def test_无依据功能和材质声明被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        forbidden_claims = (
            "防水",
            "防风",
            "透气",
            "保暖",
            "速干",
            "抗皱",
            "真皮",
            "棉质",
            "镀金",
            "塑料",
        )
        for claim in forbidden_claims:
            with self.subTest(claim=claim):
                result = valid_vlm_result()
                result["retrieval_text"] = f"蓝色连衣裙，具有{claim}特性"
                with self.assertRaises(ValueError):
                    _validate_vlm_result(result)

    def test_品牌和价格声明被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        for claim in ("品牌", "价格"):
            with self.subTest(claim=claim):
                result = valid_vlm_result()
                result["retrieval_text"] = f"蓝色连衣裙，包含{claim}信息"
                with self.assertRaises(ValueError):
                    _validate_vlm_result(result)

    def test_uncertain_fields_缺少_material_被拒绝(self):
        from src.data.polyvore_vlm_enrich import _validate_vlm_result

        result = valid_vlm_result()
        result["uncertain_fields"] = []
        with self.assertRaises(ValueError):
            _validate_vlm_result(result)


class PolyvoreVlmEnrichRunnerTest(unittest.TestCase):
    def test_limit_必须在一到五之间(self):
        from src.data.polyvore_vlm_enrich import enrich_polyvore_sample

        for limit in (0, 6):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    enrich_polyvore_sample(limit=limit)

    def test_单条模拟增强保留可信定位字段(self):
        import src.data.polyvore_vlm_enrich as enrich_module

        manifest_record = {
            "item_id": "175787103",
            "bucket": "shopping-qna",
            "object_key": "polyvore/items/175787103.jpg",
            "source_file": "175787103.jpg",
            "source_split": "nondisjoint/validation",
        }
        model_result = valid_vlm_result()
        model_result["item_id"] = "模型错误编号"
        model_result.update(
            {
                "bucket": "模型错误桶",
                "object_key": "模型错误对象键",
                "source_file": "模型错误来源.jpg",
                "source_split": "模型错误分片",
            }
        )

        response = MagicMock()
        response.read.return_value = minimal_jpeg_bytes()
        client = MagicMock()
        client.get_object.return_value = response

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = temp_path / "manifest.jsonl"
            metadata_path = temp_path / "metadata.json"
            categories_path = temp_path / "categories.csv"
            output_path = temp_path / "enriched.jsonl"
            manifest_path.write_text(
                json.dumps(manifest_record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "175787103": {
                            "url_name": "blue-dress",
                            "semantic_category": "dresses",
                            "category_id": "1",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            categories_path.write_text("1,day dresses\n", encoding="utf-8")

            fake_dashscope_client = ModuleType("src.llm.dashscope_client")
            fake_dashscope_client.describe_image = MagicMock(
                return_value=json.dumps(model_result, ensure_ascii=False)
            )
            with patch.dict(
                sys.modules,
                {"src.llm.dashscope_client": fake_dashscope_client},
            ), patch.object(
                enrich_module,
                "_validate_vlm_result",
                side_effect=lambda result: result,
                create=True,
            ):
                result = enrich_module.enrich_polyvore_sample(
                    manifest_path=manifest_path,
                    metadata_path=metadata_path,
                    categories_path=categories_path,
                    output_path=output_path,
                    limit=1,
                    client=client,
                )
            enriched = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result["enriched"], 1)
        for field in ("bucket", "object_key", "source_file", "source_split"):
            self.assertEqual(enriched[field], manifest_record[field])
        self.assertEqual(enriched["item_id"], manifest_record["item_id"])
        self.assertTrue(EXPECTED_VLM_FIELDS.issubset(enriched))
        client.get_object.assert_called_once_with(
            manifest_record["bucket"], manifest_record["object_key"]
        )


if __name__ == "__main__":
    unittest.main()
