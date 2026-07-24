import unittest


class FakeResult:
    def __iter__(self):
        return iter(
            [
                {
                    "candidate_item_id": "candidate-1",
                    "shared_outfit_ids": ["outfit-1"],
                    "cooccurrence_count": 1,
                }
            ]
        )


class FakeSession:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return FakeResult()


class FakeDriver:
    def __init__(self):
        self.fake_session = FakeSession()
        self.closed = False

    def session(self):
        return self.fake_session

    def close(self):
        self.closed = True


class Neo4jOutfitProviderTest(unittest.TestCase):
    def test_query_返回现有候选结构并透传参数(self):
        from src.graph.neo4j_outfit_provider import Neo4jOutfitProvider

        driver = FakeDriver()
        provider = Neo4jOutfitProvider(driver=driver)

        results = provider.query("anchor-1", 3)

        self.assertEqual(results[0]["candidate_item_id"], "candidate-1")
        self.assertEqual(results[0]["shared_outfit_ids"], ["outfit-1"])
        self.assertEqual(results[0]["cooccurrence_count"], 1)
        self.assertEqual(
            driver.fake_session.calls[0][1],
            {"anchor_item_id": "anchor-1", "top_k": 3},
        )

    def test_close_关闭_driver(self):
        from src.graph.neo4j_outfit_provider import Neo4jOutfitProvider

        driver = FakeDriver()
        provider = Neo4jOutfitProvider(driver=driver)

        provider.close()

        self.assertTrue(driver.closed)

    def test_query_pairwise_仅查询不同输入图候选组合(self):
        from src.graph.neo4j_outfit_provider import (
            PAIRWISE_COOCCURRENCE_CYPHER,
            Neo4jOutfitProvider,
        )

        driver = FakeDriver()
        provider = Neo4jOutfitProvider(driver=driver)

        provider.query_pairwise([["a1", "a2"], ["b1", "b2"]])

        query, parameters = driver.fake_session.calls[0]
        self.assertEqual(query, PAIRWISE_COOCCURRENCE_CYPHER)
        self.assertIn(
            "candidate_a.image_index < candidate_b.image_index",
            query,
        )
        self.assertEqual(
            parameters["candidates"],
            [
                {"image_index": 0, "item_id": "a1"},
                {"image_index": 0, "item_id": "a2"},
                {"image_index": 1, "item_id": "b1"},
                {"image_index": 1, "item_id": "b2"},
            ],
        )


    def test_query_replacement_cooccurrences_只读查询保留项与候选(self):
        from src.graph.neo4j_outfit_provider import (
            REPLACEMENT_COOCCURRENCE_CYPHER,
            Neo4jOutfitProvider,
        )

        driver = FakeDriver()
        provider = Neo4jOutfitProvider(driver=driver)

        provider.query_replacement_cooccurrences(
            ["anchor", "locked"],
            ["candidate-1"],
        )

        query, parameters = driver.fake_session.calls[0]
        self.assertEqual(query, REPLACEMENT_COOCCURRENCE_CYPHER)
        self.assertEqual(
            parameters,
            {
                "retained_item_ids": ["anchor", "locked"],
                "candidate_item_ids": ["candidate-1"],
            },
        )
        self.assertNotRegex(
            query.upper(),
            r"\b(CREATE|MERGE|SET|DELETE|REMOVE)\b",
        )


if __name__ == "__main__":
    unittest.main()
