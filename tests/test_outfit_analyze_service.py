import unittest


class FakeObjectResponse:
    def __init__(self, content):
        self.content = content
        self.closed = False
        self.released = False

    def read(self):
        return self.content

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakeMinioClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def get_object(self, bucket, object_key):
        self.calls.append((bucket, object_key))
        response = FakeObjectResponse(object_key.encode("utf-8"))
        self.responses.append(response)
        return response


class FakeEmbeddings:
    def __init__(self):
        self.images = []

    def embed_image(self, image_bytes):
        self.images.append(image_bytes)
        return [float(len(self.images)), 0.0]


class FakeCollection:
    def __init__(self):
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ids": [["101", "102", "103"]],
            "distances": [[0.1, 0.4, 0.8]],
            "metadatas": [[
                {"item_id": "101"},
                {"item_id": "102"},
                {"item_id": "103"},
            ]],
        }


class FakeOutfitProvider:
    def __init__(self, evidence=None):
        self.evidence = evidence or []
        self.calls = []

    def query_pairwise(self, candidate_groups):
        self.calls.append(candidate_groups)
        return self.evidence


class OutfitAnalyzeServiceTest(unittest.TestCase):
    def test_每张图只读匹配_top3_且补齐商品元数据(self):
        from src.outfit_analyze_service import OutfitAnalyzeService

        minio_client = FakeMinioClient()
        embeddings = FakeEmbeddings()
        collection = FakeCollection()

        def resolver(item_id):
            return {
                "found": True,
                "item_id": item_id,
                "bucket": "shopping-qna",
                "object_key": f"polyvore/items/{item_id}.jpg",
                "retrieval_text": "",
                "category": "下装",
                "sub_category": "短裤",
                "colors": ["蓝色"],
                "style": [],
                "scene": [],
            }

        service = OutfitAnalyzeService(
            minio_client=minio_client,
            bucket="shopping-qna",
            image_embeddings=embeddings,
            collection=collection,
            resolver=resolver,
            outfit_provider=FakeOutfitProvider(),
        )

        result = service.analyze(
            ["uploads/demo/1.jpg", "uploads/demo/2.jpg"]
        )

        self.assertEqual(result["analysis_stage"], "outfit_assessment")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(
            minio_client.calls,
            [
                ("shopping-qna", "uploads/demo/1.jpg"),
                ("shopping-qna", "uploads/demo/2.jpg"),
            ],
        )
        for item in result["items"]:
            self.assertEqual(len(item["matches"]), 3)
            self.assertEqual(
                [match["rank"] for match in item["matches"]],
                [1, 2, 3],
            )
            self.assertEqual(item["matches"][0]["item_id"], "101")
            self.assertEqual(item["matches"][0]["category"], "下装")
            self.assertEqual(item["matches"][0]["colors"], ["蓝色"])
        self.assertTrue(
            all(response.closed and response.released for response in minio_client.responses)
        )
        self.assertTrue(
            all(call["n_results"] == 3 for call in collection.calls)
        )
        self.assertFalse(hasattr(collection, "upsert"))
        self.assertEqual(result["score"], 35)
        self.assertEqual(result["evidence_level"], "weak")
        self.assertEqual(result["rule_scores"]["graph_score"], 0)
        self.assertIn("图关系证据不足", result["warnings"])

    def test_跨图片候选共现产生_strong_证据和评分(self):
        from src.outfit_analyze_service import OutfitAnalyzeService

        provider = FakeOutfitProvider(
            [
                {
                    "item_a": "101",
                    "item_b": "102",
                    "shared_outfit_ids": ["o1", "o2"],
                    "cooccurrence_count": 2,
                }
            ]
        )

        def resolver(item_id):
            is_first = item_id == "101"
            return {
                "found": True,
                "item_id": item_id,
                "bucket": "shopping-qna",
                "object_key": f"polyvore/items/{item_id}.jpg",
                "retrieval_text": "",
                "category": "上装" if is_first else "下装",
                "sub_category": "衬衫" if is_first else "裤子",
                "colors": ["蓝色"],
                "style": ["休闲"],
                "scene": [],
            }

        service = OutfitAnalyzeService(
            minio_client=FakeMinioClient(),
            bucket="shopping-qna",
            image_embeddings=FakeEmbeddings(),
            collection=FakeCollection(),
            resolver=resolver,
            outfit_provider=provider,
        )

        result = service.analyze(["a.jpg", "b.jpg"])

        self.assertEqual(
            provider.calls,
            [[["101", "102", "103"], ["101", "102", "103"]]],
        )
        self.assertEqual(result["rule_scores"]["graph_score"], 30)
        self.assertGreaterEqual(result["score"], 75)
        self.assertEqual(result["evidence_level"], "strong")
        self.assertEqual(result["graph_evidence"][0]["item_a"], "101")

    def test_缺颜色和风格时给中性分且不抛错(self):
        from src.outfit_analyze_service import OutfitAnalyzeService

        def resolver(item_id):
            return {
                "found": True,
                "item_id": item_id,
                "bucket": "shopping-qna",
                "object_key": f"polyvore/items/{item_id}.jpg",
                "retrieval_text": "",
                "category": "",
                "sub_category": "",
                "colors": [],
                "style": [],
                "scene": [],
            }

        service = OutfitAnalyzeService(
            minio_client=FakeMinioClient(),
            bucket="shopping-qna",
            image_embeddings=FakeEmbeddings(),
            collection=FakeCollection(),
            resolver=resolver,
            outfit_provider=FakeOutfitProvider(),
        )

        result = service.analyze(["a.jpg", "b.jpg"])

        self.assertEqual(result["rule_scores"]["color_score"], 10)
        self.assertEqual(result["rule_scores"]["style_score"], 10)
        self.assertEqual(result["evidence_level"], "weak")


if __name__ == "__main__":
    unittest.main()
