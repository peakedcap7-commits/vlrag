from src.performance import measure


OUTFIT_QUERY_CYPHER = """
MATCH (anchor:Item {item_id: $anchor_item_id})
      -[:IN_OUTFIT]->(outfit:Outfit)
      <-[:IN_OUTFIT]-(candidate:Item)
WHERE candidate.item_id <> anchor.item_id
WITH candidate, outfit
ORDER BY outfit.outfit_id
WITH candidate, collect(outfit.outfit_id) AS shared_outfit_ids
RETURN candidate.item_id AS candidate_item_id,
       shared_outfit_ids,
       size(shared_outfit_ids) AS cooccurrence_count
ORDER BY cooccurrence_count DESC, candidate_item_id ASC
LIMIT $top_k
"""

PAIRWISE_COOCCURRENCE_CYPHER = """
UNWIND $candidates AS candidate_a
UNWIND $candidates AS candidate_b
WITH candidate_a, candidate_b
WHERE candidate_a.image_index < candidate_b.image_index
MATCH (item_a:Item {item_id: candidate_a.item_id})
      -[:IN_OUTFIT]->(outfit:Outfit)
      <-[:IN_OUTFIT]-(item_b:Item {item_id: candidate_b.item_id})
WITH candidate_a.item_id AS item_a,
     candidate_b.item_id AS item_b,
     collect(DISTINCT outfit.outfit_id) AS shared_outfit_ids
RETURN item_a,
       item_b,
       shared_outfit_ids,
       size(shared_outfit_ids) AS cooccurrence_count
ORDER BY cooccurrence_count DESC, item_a ASC, item_b ASC
"""

REPLACEMENT_COOCCURRENCE_CYPHER = """
UNWIND $retained_item_ids AS retained_item_id
UNWIND $candidate_item_ids AS candidate_item_id
MATCH (retained:Item {item_id: retained_item_id})
      -[:IN_OUTFIT]->(outfit:Outfit)
      <-[:IN_OUTFIT]-(candidate:Item {item_id: candidate_item_id})
WHERE retained.item_id <> candidate.item_id
WITH retained.item_id AS retained_item_id,
     candidate.item_id AS candidate_item_id,
     collect(DISTINCT outfit.outfit_id) AS shared_outfit_ids
RETURN retained_item_id,
       candidate_item_id,
       shared_outfit_ids,
       size(shared_outfit_ids) AS cooccurrence_count
ORDER BY cooccurrence_count DESC,
         retained_item_id ASC,
         candidate_item_id ASC
"""


class Neo4jOutfitProvider:
    """通过 Neo4j 查询同 outfit 候选，不执行降级。"""

    def __init__(self, uri=None, user=None, password=None, driver=None):
        if driver is None:
            if not uri or not user or not password:
                raise ValueError("Neo4j 连接配置不完整")
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
        self.driver = driver

    def query(self, anchor_item_id, top_k):
        """按共现次数和商品 ID 稳定返回候选。"""
        with measure("neo4j_query_ms", operation="recommend"):
            with self.driver.session() as session:
                return [
                    dict(record)
                    for record in session.run(
                        OUTFIT_QUERY_CYPHER,
                        anchor_item_id=str(anchor_item_id),
                        top_k=top_k,
                    )
                ]

    def query_pairwise(self, candidate_groups):
        """只读查询不同输入图候选之间的 outfit 共现。"""
        candidates = [
            {"image_index": image_index, "item_id": str(item_id)}
            for image_index, item_ids in enumerate(candidate_groups)
            for item_id in item_ids
        ]
        with measure("neo4j_query_ms", operation="outfit_analyze"):
            with self.driver.session() as session:
                return [
                    dict(record)
                    for record in session.run(
                        PAIRWISE_COOCCURRENCE_CYPHER,
                        candidates=candidates,
                    )
                ]

    def query_replacement_cooccurrences(
        self,
        retained_item_ids,
        candidate_item_ids,
    ):
        """只读查询替换候选与当前保留单品之间的 outfit 共现。"""
        with measure("neo4j_query_ms", operation="outfit_revise"):
            with self.driver.session() as session:
                return [
                    dict(record)
                    for record in session.run(
                        REPLACEMENT_COOCCURRENCE_CYPHER,
                        retained_item_ids=[
                            str(item_id) for item_id in retained_item_ids
                        ],
                        candidate_item_ids=[
                            str(item_id) for item_id in candidate_item_ids
                        ],
                    )
                ]

    def close(self):
        """关闭底层 Neo4j driver。"""
        self.driver.close()
