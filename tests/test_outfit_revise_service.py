import unittest


class OutfitReviseServiceTest(unittest.TestCase):
    def setUp(self):
        from src.outfit_revise_service import OutfitReviseService

        self.service = OutfitReviseService()

    def test_解析排除与偏好品类(self):
        result = self.service.parse(
            "不要裙子，换成裤子",
            {"anchor_item_id": "1"},
        )

        self.assertEqual(result["exclude_categories"], ["裙子"])
        self.assertEqual(result["prefer_categories"], ["裤子"])
        self.assertEqual(result["rewrite_scope"], "partial")

    def test_标准化半身裙与牛仔裤(self):
        result = self.service.parse(
            "不要半身裙，换成牛仔裤",
            {"anchor_item_id": "1"},
        )

        self.assertEqual(result["exclude_categories"], ["裙子"])
        self.assertEqual(result["prefer_categories"], ["裤子"])
        self.assertEqual(
            result["normalized_constraints"]["exclude_categories"],
            ["裙子"],
        )

    def test_解析保留项与正式风格(self):
        result = self.service.parse(
            "保留这件上衣，更正式一点",
            {
                "anchor_item_id": "top-1",
                "locked_item_ids": ["locked-1"],
            },
        )

        self.assertEqual(result["keep_items"], ["top-1", "locked-1"])
        self.assertEqual(result["style_shift"], "more_formal")
        self.assertEqual(result["rewrite_scope"], "partial")

    def test_重新搭一套解析为全量改写(self):
        result = self.service.parse(
            "重新搭一套",
            {"candidate_item_ids": ["1", "2"]},
        )

        self.assertEqual(result["rewrite_scope"], "full")

    def test_颜色偏好不包含排除项颜色(self):
        result = self.service.parse(
            "换成蓝色裤子，不要黑色裙子，蓝色更好",
            {"anchor_item_id": "1"},
        )

        self.assertEqual(result["prefer_colors"], ["蓝色"])

    def test_保留上衣在唯一匹配时绑定商品(self):
        result = self.service.parse(
            "保留上衣",
            {
                "item_metadata": [
                    {
                        "item_id": "top-1",
                        "category": "上装",
                        "sub_category": "衬衫",
                    },
                    {
                        "item_id": "skirt-1",
                        "category": "下装",
                        "sub_category": "半身裙",
                    },
                ]
            },
        )

        self.assertEqual(result["bound_keep_item_ids"], ["top-1"])
        self.assertFalse(result["needs_clarification"])
        self.assertEqual(result["clarification_question"], "")

    def test_保留上衣在多个匹配时追问(self):
        result = self.service.parse(
            "保留上衣",
            {
                "item_metadata": [
                    {
                        "item_id": "top-1",
                        "category": "上装",
                        "sub_category": "衬衫",
                    },
                    {
                        "item_id": "top-2",
                        "category": "上装",
                        "sub_category": "T恤",
                    },
                ]
            },
        )

        self.assertTrue(result["needs_clarification"])
        self.assertIn("哪一件上衣", result["clarification_question"])
        self.assertEqual(result["bound_keep_item_ids"], [])

    def test_换掉这个没有选中商品时追问(self):
        result = self.service.parse(
            "换掉这个",
            {"candidate_item_ids": ["1", "2"]},
        )

        self.assertTrue(result["needs_clarification"])
        self.assertIn("选择", result["clarification_question"])
        self.assertEqual(result["bound_exclude_item_ids"], [])

    def test_保留与排除同一商品时返回冲突追问(self):
        result = self.service.parse(
            "保留这条裙子，但不要裙子",
            {
                "selected_item_ids": ["skirt-1"],
                "item_metadata": [
                    {
                        "item_id": "skirt-1",
                        "category": "下装",
                        "sub_category": "裙装",
                    }
                ],
            },
        )

        self.assertTrue(result["needs_clarification"])
        self.assertIn("冲突", result["clarification_question"])
        self.assertEqual(result["bound_keep_item_ids"], ["skirt-1"])
        self.assertEqual(result["bound_exclude_item_ids"], ["skirt-1"])
        self.assertLess(result["confidence"], 0.5)


if __name__ == "__main__":
    unittest.main()
