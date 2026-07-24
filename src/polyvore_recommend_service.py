from dataclasses import dataclass, field
from pathlib import Path

from src.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, OUTFIT_PROVIDER
from src.polyvore_recommend import recommend_polyvore_query
from src.polyvore_retrieval import retrieve_polyvore_query


@dataclass(frozen=True)
class PolyvoreRecommendConfig:
    """Polyvore 推荐服务的只读资源路径。"""

    persist_dir: Path = Path("chroma_data")
    valid_path: Path = Path(r"D:\datasets\polyvore-outfits\nondisjoint\valid.json")
    sample_path: Path = Path("data/processed/polyvore_items_sample.jsonl")
    neo4j_manifest_path: Path = Path(
        "data/processed/polyvore_neo4j_items_manifest.jsonl"
    )
    retrieval_manifest_path: Path = Path(
        "data/processed/polyvore_neo4j_items_retrieval.jsonl"
    )
    enriched_path: Path = Path(
        "data/processed/polyvore_items_enriched_sample.jsonl"
    )
    outfit_provider: str = OUTFIT_PROVIDER
    neo4j_uri: str = NEO4J_URI
    neo4j_user: str = NEO4J_USER
    neo4j_password: str | None = field(default=NEO4J_PASSWORD, repr=False)


class PolyvoreRecommendService:
    """编排检索、outfit 扩展和商品解析。"""

    def __init__(
        self,
        retrieval,
        outfit_provider,
        resolver,
        image_embeddings=None,
        text_embeddings=None,
        chroma_client=None,
    ):
        self.retrieval = retrieval
        self.outfit_provider = outfit_provider
        self.resolver = resolver
        self.image_embeddings = image_embeddings
        self.text_embeddings = text_embeddings
        self.chroma_client = chroma_client

    def recommend(self, query, top_k, retrieval_limit):
        """执行一次共享推荐编排。"""
        return recommend_polyvore_query(
            query=query,
            retrieval=lambda value: self.retrieval(value, retrieval_limit),
            outfit_query=lambda anchor_item_id, _item_index, _outfit_index: (
                self.outfit_provider.query(anchor_item_id, top_k)
            ),
            item_to_outfit_ids=None,
            outfit_to_item_ids=None,
            top_k=top_k,
            resolver=self.resolver,
        )

    def close(self):
        """释放推荐服务持有的外部资源。"""
        self.outfit_provider.close()


def build_polyvore_recommend_service(config=None):
    """一次性组装推荐服务所需的只读依赖。"""
    config = config or PolyvoreRecommendConfig()

    import chromadb

    from src.data.polyvore_item_resolver import (
        build_item_index,
        merge_item_indexes,
        resolve_item,
    )
    from src.embeddings.chinese_clip import ChineseCLIPEmbeddings
    from src.embeddings.dashscope_emb import DashScopeEmbeddings
    from src.graph.neo4j_outfit_provider import Neo4jOutfitProvider

    if config.outfit_provider != "neo4j":
        raise ValueError("OUTFIT_PROVIDER 必须配置为 neo4j")

    chroma_client = chromadb.PersistentClient(path=str(config.persist_dir))
    text_embeddings = DashScopeEmbeddings()
    image_embeddings = ChineseCLIPEmbeddings()
    outfit_provider = Neo4jOutfitProvider(
        uri=config.neo4j_uri,
        user=config.neo4j_user,
        password=config.neo4j_password,
    )
    neo4j_index = build_item_index(jsonl_path=config.neo4j_manifest_path)
    sample_index = build_item_index(jsonl_path=config.sample_path)
    item_index = merge_item_indexes(neo4j_index, sample_index)
    enriched_index = build_item_index(jsonl_path=config.enriched_path)

    def retrieval(query, limit):
        return retrieve_polyvore_query(
            query=query,
            chroma_client=chroma_client,
            text_embeddings=text_embeddings,
            image_embeddings=image_embeddings,
            limit=limit,
            enriched_path=config.retrieval_manifest_path,
        )

    def resolver(item_id):
        return resolve_item(item_id, item_index, enriched_index)

    return PolyvoreRecommendService(
        retrieval=retrieval,
        outfit_provider=outfit_provider,
        resolver=resolver,
        image_embeddings=image_embeddings,
        text_embeddings=text_embeddings,
        chroma_client=chroma_client,
    )
