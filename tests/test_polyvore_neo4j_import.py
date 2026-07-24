import unittest


class PolyvoreNeo4jImportTest(unittest.TestCase):
    def test_切片优先覆盖_enriched并补足目标套数(self):
        from src.data.polyvore_neo4j_import import select_outfit_slice

        outfits = [
            {"set_id": "30", "items": [{"item_id": "e3"}, {"item_id": "x3"}]},
            {"set_id": "10", "items": [{"item_id": "e1"}, {"item_id": "x1"}]},
            {"set_id": "20", "items": [{"item_id": "e2"}, {"item_id": "x2"}]},
            {"set_id": "40", "items": [{"item_id": "m1"}, {"item_id": "x4"}]},
            {"set_id": "50", "items": [{"item_id": "outside"}]},
        ]

        selected = select_outfit_slice(
            outfits=outfits,
            manifest_item_ids={"e1", "e2", "e3", "m1"},
            enriched_item_ids={"e1", "e2", "e3"},
            target_outfits=4,
        )

        self.assertEqual([item["outfit_id"] for item in selected], ["10", "20", "30", "40"])
        selected_item_ids = {
            item_id
            for outfit in selected
            for item_id in outfit["item_ids"]
        }
        self.assertTrue({"e1", "e2", "e3"}.issubset(selected_item_ids))

    def test_关系行去重且标识保持字符串(self):
        from src.data.polyvore_neo4j_import import build_relation_rows

        rows = build_relation_rows(
            [{"outfit_id": "100", "item_ids": ["1", "1", "2"]}]
        )

        self.assertEqual(
            rows,
            [
                {"outfit_id": "100", "item_id": "1"},
                {"outfit_id": "100", "item_id": "2"},
            ],
        )

    def test_导入_cypher使用_merge创建点和边(self):
        from src.data.polyvore_neo4j_import import UPSERT_CYPHER

        self.assertIn("MERGE (item:Item {item_id: row.item_id})", UPSERT_CYPHER)
        self.assertIn("MERGE (outfit:Outfit {outfit_id: row.outfit_id})", UPSERT_CYPHER)
        self.assertIn("MERGE (item)-[relation:IN_OUTFIT]->(outfit)", UPSERT_CYPHER)

    def test_统计_cypher使用显式空变量作用域(self):
        from src.data.polyvore_neo4j_import import COUNT_CYPHER

        self.assertEqual(COUNT_CYPHER.count("CALL () {"), 3)


if __name__ == "__main__":
    unittest.main()
