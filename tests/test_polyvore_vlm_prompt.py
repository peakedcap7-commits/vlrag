import unittest


class PolyvoreVlmPromptTest(unittest.TestCase):
    def test_动态注入元数据并约束视觉分析输出(self):
        from src.llm.polyvore_vlm_prompt import build_polyvore_vlm_prompt

        metadata = {
            "item_id": "175787103",
            "url_name": "unique-floral-midi-dress",
            "semantic_category": "unique-dresses",
            "category_name": "unique-day-dresses",
            "bucket": "unique-shopping-bucket",
            "object_key": "polyvore/items/unique-175787103.jpg",
        }

        prompt = build_polyvore_vlm_prompt(metadata)
        normalized_prompt = " ".join(prompt.split())

        for value in metadata.values():
            self.assertIn(value, prompt)

        self.assertIn("metadata 仅用于辅助", normalized_prompt)
        self.assertIn("冲突以图片可见内容为准", normalized_prompt)

        forbidden_contents = (
            "防水",
            "防风",
            "透气",
            "保暖",
            "速干",
            "抗皱",
            "品牌",
            "价格",
            "性别",
            "人群",
            "不可见材质",
        )
        for forbidden_content in forbidden_contents:
            with self.subTest(forbidden_content=forbidden_content):
                self.assertIn(f"禁止编造{forbidden_content}", normalized_prompt)

        expected_fields = (
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
        )
        for field in expected_fields:
            self.assertIn(f'"{field}"', prompt)

        self.assertIn("retrieval_text 使用中文自然语言", normalized_prompt)
        self.assertIn("用于中文向量检索", normalized_prompt)
        self.assertIn("material 必须固定为空字符串", normalized_prompt)
        self.assertIn("uncertain_fields 必须包含 material", normalized_prompt)
        self.assertIn("retrieval_text 禁止包含材质成分断言", normalized_prompt)


if __name__ == "__main__":
    unittest.main()
