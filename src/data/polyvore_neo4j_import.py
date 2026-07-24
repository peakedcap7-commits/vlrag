import json
from pathlib import Path


DEFAULT_VALID_PATH = Path(r"D:\datasets\polyvore-outfits\nondisjoint\valid.json")
DEFAULT_MANIFEST_PATH = Path("data/processed/polyvore_items_sample.jsonl")
DEFAULT_ENRICHED_PATH = Path("data/processed/polyvore_items_enriched_sample.jsonl")

ITEM_CONSTRAINT_CYPHER = """
CREATE CONSTRAINT item_item_id_unique IF NOT EXISTS
FOR (item:Item) REQUIRE item.item_id IS UNIQUE
"""

OUTFIT_CONSTRAINT_CYPHER = """
CREATE CONSTRAINT outfit_outfit_id_unique IF NOT EXISTS
FOR (outfit:Outfit) REQUIRE outfit.outfit_id IS UNIQUE
"""

UPSERT_CYPHER = """
UNWIND $rows AS row
MERGE (item:Item {item_id: row.item_id})
ON CREATE SET item.created_by_batch = $batch_id
MERGE (outfit:Outfit {outfit_id: row.outfit_id})
ON CREATE SET outfit.created_by_batch = $batch_id
MERGE (item)-[relation:IN_OUTFIT]->(outfit)
ON CREATE SET relation.created_by_batch = $batch_id
RETURN count(*) AS processed_rows
"""

COUNT_CYPHER = """
CALL () { MATCH (item:Item) RETURN count(item) AS items }
CALL () { MATCH (outfit:Outfit) RETURN count(outfit) AS outfits }
CALL () { MATCH ()-[relation:IN_OUTFIT]->() RETURN count(relation) AS relationships }
RETURN items, outfits, relationships
"""

ANCHOR_QUERY_CYPHER = """
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


def load_item_ids(jsonl_path):
    """读取 JSONL 中的非空字符串 item_id。"""
    return {
        str(record["item_id"]).strip()
        for line in Path(jsonl_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if str(record.get("item_id", "")).strip()
    }


def _normalize_outfit(outfit):
    outfit_id = str(outfit.get("set_id", "")).strip()
    item_ids = sorted(
        {
            str(item.get("item_id", "")).strip()
            for item in outfit.get("items", [])
            if str(item.get("item_id", "")).strip()
        }
    )
    if not outfit_id or not item_ids:
        return None
    return {"outfit_id": outfit_id, "item_ids": item_ids}


def select_outfit_slice(
    outfits,
    manifest_item_ids,
    enriched_item_ids,
    target_outfits=40,
):
    """优先覆盖 enriched 商品，再补足包含 manifest 商品的 outfit。"""
    manifest_item_ids = {str(value).strip() for value in manifest_item_ids}
    enriched_item_ids = {str(value).strip() for value in enriched_item_ids}
    normalized = [item for outfit in outfits if (item := _normalize_outfit(outfit))]
    eligible = [
        outfit
        for outfit in normalized
        if manifest_item_ids.intersection(outfit["item_ids"])
    ]
    priority = sorted(
        [
            outfit
            for outfit in eligible
            if enriched_item_ids.intersection(outfit["item_ids"])
        ],
        key=lambda item: item["outfit_id"],
    )
    priority_ids = {item["outfit_id"] for item in priority}
    remaining = sorted(
        [item for item in eligible if item["outfit_id"] not in priority_ids],
        key=lambda item: item["outfit_id"],
    )
    selected = (priority + remaining)[:target_outfits]
    covered = {
        item_id
        for outfit in selected
        for item_id in outfit["item_ids"]
        if item_id in enriched_item_ids
    }
    missing = sorted(enriched_item_ids - covered)
    if missing:
        raise ValueError(f"切片未覆盖 enriched item：{missing}")
    if len(selected) != target_outfits:
        raise ValueError(f"可用 outfit 不足 {target_outfits} 套")
    return selected


def build_relation_rows(outfits):
    """生成稳定且去重的 Item-Outfit 关系行。"""
    return [
        {"outfit_id": str(outfit["outfit_id"]), "item_id": str(item_id)}
        for outfit in outfits
        for item_id in sorted(set(outfit["item_ids"]))
    ]


def prepare_import_rows(
    valid_path=DEFAULT_VALID_PATH,
    manifest_path=DEFAULT_MANIFEST_PATH,
    enriched_path=DEFAULT_ENRICHED_PATH,
    target_outfits=40,
):
    """读取本地文件并准备确定性导入切片。"""
    outfits = json.loads(Path(valid_path).read_text(encoding="utf-8"))
    manifest_item_ids = load_item_ids(manifest_path)
    enriched_item_ids = load_item_ids(enriched_path)
    selected = select_outfit_slice(
        outfits,
        manifest_item_ids,
        enriched_item_ids,
        target_outfits,
    )
    rows = build_relation_rows(selected)
    return {
        "rows": rows,
        "selected_outfits": len(selected),
        "selected_items": len({row["item_id"] for row in rows}),
        "selected_relationships": len(rows),
        "enriched_covered": len(
            enriched_item_ids.intersection({row["item_id"] for row in rows})
        ),
        "enriched_total": len(enriched_item_ids),
    }


def import_rows(driver, rows, batch_id):
    """创建约束并以 MERGE 幂等写入关系行。"""
    with driver.session() as session:
        session.run(ITEM_CONSTRAINT_CYPHER).consume()
        session.run(OUTFIT_CONSTRAINT_CYPHER).consume()
        processed = session.run(
            UPSERT_CYPHER,
            rows=rows,
            batch_id=batch_id,
        ).single()["processed_rows"]
        counts = dict(session.run(COUNT_CYPHER).single())
    return {"processed_rows": processed, **counts}


def query_anchor_candidates(driver, anchor_item_id, top_k=10):
    """查询 anchor 同 outfit 的候选商品。"""
    with driver.session() as session:
        return [
            dict(record)
            for record in session.run(
                ANCHOR_QUERY_CYPHER,
                anchor_item_id=str(anchor_item_id),
                top_k=top_k,
            )
        ]


def create_neo4j_driver(uri, user, password):
    """按需创建 Neo4j driver，避免纯数据测试依赖外部服务。"""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver
