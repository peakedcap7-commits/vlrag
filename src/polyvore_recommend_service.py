import json
from dataclasses import dataclass
from pathlib import Path

from src.polyvore_recommend import recommend_polyvore_query
from src.polyvore_retrieval import retrieve_polyvore_query


@dataclass(frozen=True)
class PolyvoreRecommendConfig:
    """Polyvore 推荐服务的只读资源路径。"""

    persist_dir: Path = Path("chroma_data")
    valid_path: Path = Path(r"D:\datasets\polyvore-outfits\nondisjoint\valid.json")
    sample_path: Path = Path("data/processed/polyvore_items_sample.jsonl")
    enriched_path: Path = Path(
        "data/processed/polyvore_items_enriched_sample.jsonl"
    )


class PolyvoreRecommendService:
    """编排检索、outfit 扩展和商品解析。"""

    def __init__(
        self,
        retrieval,
        outfit_query,
        item_to_outfit_ids,
        outfit_to_item_ids,
        resolver,
    ):
        self.retrieval = retrieval
        self.outfit_query = outfit_query
        self.item_to_outfit_ids = item_to_outfit_ids
        self.outfit_to_item_ids = outfit_to_item_ids
        self.resolver = resolver

    def recommend(self, query, top_k, retrieval_limit):
        """执行一次共享推荐编排。"""
        return recommend_polyvore_query(
            query=query,
            retrieval=lambda value: self.retrieval(value, retrieval_limit),
            outfit_query=self.outfit_query,
            item_to_outfit_ids=self.item_to_outfit_ids,
            outfit_to_item_ids=self.outfit_to_item_ids,
            top_k=top_k,
            resolver=self.resolver,
        )


def build_polyvore_recommend_service(config=None):
    """一次性组装推荐服务所需的只读依赖。"""
    config = config or PolyvoreRecommendConfig()

    import chromadb

    from src.data.polyvore_item_resolver import build_item_index, resolve_item
    from src.embeddings.chinese_clip import ChineseCLIPEmbeddings
    from src.embeddings.dashscope_emb import DashScopeEmbeddings
    from src.graph.polyvore_outfit_graph import (
        build_outfit_indexes,
        query_outfit_candidates,
    )

    chroma_client = chromadb.PersistentClient(path=str(config.persist_dir))
    text_embeddings = DashScopeEmbeddings()
    image_embeddings = ChineseCLIPEmbeddings()
    outfits = json.loads(Path(config.valid_path).read_text(encoding="utf-8"))
    item_to_outfit_ids, outfit_to_item_ids = build_outfit_indexes(outfits)
    item_index = build_item_index(jsonl_path=config.sample_path)
    enriched_index = build_item_index(jsonl_path=config.enriched_path)

    def retrieval(query, limit):
        return retrieve_polyvore_query(
            query=query,
            chroma_client=chroma_client,
            text_embeddings=text_embeddings,
            image_embeddings=image_embeddings,
            limit=limit,
            enriched_path=config.enriched_path,
        )

    def resolver(item_id):
        return resolve_item(item_id, item_index, enriched_index)

    return PolyvoreRecommendService(
        retrieval=retrieval,
        outfit_query=query_outfit_candidates,
        item_to_outfit_ids=item_to_outfit_ids,
        outfit_to_item_ids=outfit_to_item_ids,
        resolver=resolver,
    )
