from src.config import MINIO_BUCKET
from src.performance import measure
from src.vectordb.chinese_clip_image_store import COLLECTION_NAME


STRONG_SCORE_THRESHOLD = 75
MEDIUM_SCORE_THRESHOLD = 50
STRONG_GRAPH_SCORE_THRESHOLD = 30
BASIC_COLORS = {
    "黑",
    "黑色",
    "白",
    "白色",
    "灰",
    "灰色",
    "米色",
    "棕色",
    "black",
    "white",
    "gray",
    "grey",
    "beige",
    "brown",
}


def _distance_to_score(distance):
    """把归一化向量的平方欧氏距离换算为余弦相似度。"""
    score = 1.0 - float(distance) / 2.0
    return round(max(-1.0, min(1.0, score)), 6)


def _score_graph(graph_evidence):
    count = sum(
        int(evidence["cooccurrence_count"])
        for evidence in graph_evidence
    )
    return 0 if count == 0 else min(40, 20 + (count - 1) * 10)


def _score_category(primary_matches):
    categories = [match["category"] for match in primary_matches]
    if not categories or any(not category for category in categories):
        return 10
    return 5 if len(set(categories)) == 1 else 20


def _score_color(primary_matches):
    color_sets = [set(match["colors"]) for match in primary_matches]
    if not color_sets or any(not colors for colors in color_sets):
        return 10
    if set.intersection(*color_sets):
        return 20
    if set.union(*color_sets) & BASIC_COLORS:
        return 15
    return 10


def _score_style(primary_matches):
    style_sets = [set(match["style"]) for match in primary_matches]
    if not style_sets or any(not styles for styles in style_sets):
        return 10
    return 20 if set.intersection(*style_sets) else 10


def _evidence_level(score, graph_score):
    if (
        graph_score >= STRONG_GRAPH_SCORE_THRESHOLD
        and score >= STRONG_SCORE_THRESHOLD
    ):
        return "strong"
    if graph_score > 0 or score >= MEDIUM_SCORE_THRESHOLD:
        return "medium"
    return "weak"


def _score_outfit(items, graph_evidence):
    primary_matches = [item["matches"][0] for item in items]
    rule_scores = {
        "graph_score": _score_graph(graph_evidence),
        "category_score": _score_category(primary_matches),
        "color_score": _score_color(primary_matches),
        "style_score": _score_style(primary_matches),
    }
    score = sum(rule_scores.values())
    warnings = []
    if not graph_evidence:
        warnings.append("图关系证据不足")
    if any(not match["colors"] for match in primary_matches):
        warnings.append("颜色信息不完整，使用中性分")
    if any(not match["style"] for match in primary_matches):
        warnings.append("风格信息不完整，使用中性分")
    return {
        "score": score,
        "evidence_level": _evidence_level(
            score,
            rule_scores["graph_score"],
        ),
        "graph_evidence": graph_evidence,
        "rule_scores": rule_scores,
        "warnings": warnings,
    }


class OutfitAnalyzeService:
    """只读匹配用户图片，不保存图片向量或修改商品库。"""

    def __init__(
        self,
        minio_client,
        bucket,
        image_embeddings,
        collection,
        resolver,
        outfit_provider,
    ):
        self.minio_client = minio_client
        self.bucket = bucket
        self.image_embeddings = image_embeddings
        self.collection = collection
        self.resolver = resolver
        self.outfit_provider = outfit_provider

    def _read_image(self, object_key):
        with measure(
            "minio_read_ms",
            operation="outfit_analyze",
        ):
            response = self.minio_client.get_object(self.bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

    def _match_image(self, image_bytes):
        with measure("clip_embed_ms", operation="outfit_analyze"):
            vector = self.image_embeddings.embed_image(image_bytes)
        with measure("chroma_query_ms", operation="outfit_analyze"):
            result = self.collection.query(
                query_embeddings=[vector],
                n_results=3,
                include=["metadatas", "distances"],
            )
        ids = result["ids"][0]
        distances = result["distances"][0]
        metadatas = result.get("metadatas", [[]])[0]
        matches = []
        for rank, (record_id, distance) in enumerate(
            zip(ids, distances),
            start=1,
        ):
            metadata = metadatas[rank - 1] if rank <= len(metadatas) else {}
            item_id = str((metadata or {}).get("item_id") or record_id)
            resolved = self.resolver(item_id)
            matches.append(
                {
                    "item_id": item_id,
                    "rank": rank,
                    "score": _distance_to_score(distance),
                    "object_key": resolved["object_key"],
                    "category": resolved["category"],
                    "sub_category": resolved["sub_category"],
                    "colors": resolved["colors"],
                    "style": resolved["style"],
                }
            )
        return matches

    def analyze(self, image_keys):
        """逐图匹配后执行跨图片共现查询与规则评分。"""
        items = [
            {
                "input_image_key": image_key,
                "matches": self._match_image(self._read_image(image_key)),
            }
            for image_key in image_keys
        ]
        graph_evidence = self.outfit_provider.query_pairwise(
            [
                [match["item_id"] for match in item["matches"]]
                for item in items
            ]
        )
        return {
            "analysis_stage": "outfit_assessment",
            "items": items,
            **_score_outfit(items, graph_evidence),
        }


def build_outfit_analyze_service(
    image_embeddings,
    chroma_client,
    resolver,
    outfit_provider,
):
    """复用推荐运行时的只读依赖组装多图匹配服务。"""
    from src.data.minio_client import create_minio_client

    return OutfitAnalyzeService(
        minio_client=create_minio_client(),
        bucket=MINIO_BUCKET,
        image_embeddings=image_embeddings,
        collection=chroma_client.get_collection(name=COLLECTION_NAME),
        resolver=resolver,
        outfit_provider=outfit_provider,
    )
