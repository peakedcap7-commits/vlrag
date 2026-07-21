import json
import math
import re
from collections import Counter
from pathlib import Path


TEXT_COLLECTION_NAME = "products_text_v3_v1"
IMAGE_COLLECTION_NAME = "products_image_cnclip_v1"
RRF_K = 60
DEFAULT_ENRICHED_PATH = Path("data/processed/polyvore_items_enriched_sample.jsonl")
RULE_FIELDS = (
    ("colors", 0.003),
    ("category", 0.002),
    ("sub_category", 0.003),
    ("style", 0.002),
    ("details", 0.001),
    ("scene", 0.001),
)


def _deduplicate_ranked(results):
    """同路重复 item_id 只保留最高名次。"""
    ranked = {}
    for rank, item in enumerate(results, start=1):
        item_id = str(item["item_id"])
        if item_id not in ranked:
            ranked[item_id] = (rank, item)
    return ranked


def fuse_ranked_results(
    text_results,
    image_results,
    rrf_k=RRF_K,
    bm25_results=None,
):
    """按字符串 item_id 对三路结果执行 RRF 融合。"""
    text_ranked = _deduplicate_ranked(text_results)
    image_ranked = _deduplicate_ranked(image_results)
    bm25_ranked = _deduplicate_ranked(bm25_results or [])
    item_order = list(text_ranked)
    item_order.extend(item_id for item_id in image_ranked if item_id not in text_ranked)
    item_order.extend(
        item_id
        for item_id in bm25_ranked
        if item_id not in text_ranked and item_id not in image_ranked
    )

    fused = []
    for item_id in item_order:
        text_entry = text_ranked.get(item_id)
        image_entry = image_ranked.get(item_id)
        bm25_entry = bm25_ranked.get(item_id)
        text_rank = text_entry[0] if text_entry else None
        image_rank = image_entry[0] if image_entry else None
        bm25_rank = bm25_entry[0] if bm25_entry else None
        text_item = text_entry[1] if text_entry else None
        image_item = image_entry[1] if image_entry else None
        bm25_item = bm25_entry[1] if bm25_entry else None
        retrieval_text = (
            text_item.get("retrieval_text", "") if text_item else ""
        ) or (image_item.get("retrieval_text", "") if image_item else "") or (
            bm25_item.get("retrieval_text", "") if bm25_item else ""
        )
        object_key = (
            text_item.get("object_key", "") if text_item else ""
        ) or (image_item.get("object_key", "") if image_item else "") or (
            bm25_item.get("object_key", "") if bm25_item else ""
        )
        sources = []
        score = 0.0
        if text_rank is not None:
            sources.append("text")
            score += 1 / (rrf_k + text_rank)
        if image_rank is not None:
            sources.append("image")
            score += 1 / (rrf_k + image_rank)
        if bm25_rank is not None:
            sources.append("bm25")
            score += 1 / (rrf_k + bm25_rank)
        fused.append(
            {
                "item_id": item_id,
                "object_key": object_key,
                "retrieval_text": retrieval_text,
                "text_rank": text_rank,
                "image_rank": image_rank,
                "bm25_rank": bm25_rank,
                "rrf_score": score,
                "sources": sources,
            }
        )
    return sorted(fused, key=lambda item: item["rrf_score"], reverse=True)


def _tokenize_bm25(text):
    """提取中文单字、中文二元组与字母数字词。"""
    text = str(text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.extend(segment)
        tokens.extend(segment[index:index + 2] for index in range(len(segment) - 1))
    return tokens


def _corpus_text(item):
    """拼接增强记录中允许参与 BM25 的字段。"""
    values = []
    for field in (
        "retrieval_text",
        "category",
        "sub_category",
        "colors",
        "style",
        "details",
        "scene",
    ):
        value = item.get(field)
        if isinstance(value, list):
            values.extend(str(part) for part in value if part is not None)
        elif value is not None:
            values.append(str(value))
    return " ".join(values)


def _load_enriched_items(enriched_path):
    """一次读取本地增强 JSONL。"""
    return [
        json.loads(line)
        for line in Path(enriched_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rank_bm25_items(query, items, limit):
    """对已加载的增强记录执行 BM25 排序。"""
    if not items:
        return []
    tokenized = [_tokenize_bm25(_corpus_text(item)) for item in items]
    query_tokens = _tokenize_bm25(query)
    average_length = sum(map(len, tokenized)) / len(tokenized) or 1.0
    document_frequency = Counter(
        token for tokens in tokenized for token in set(tokens)
    )
    scores = []
    for index, tokens in enumerate(tokenized):
        frequencies = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = frequencies[token]
            if not frequency:
                continue
            frequency_in_documents = document_frequency[token]
            inverse_frequency = math.log(
                1 + (len(items) - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(tokens) / average_length
            )
            score += inverse_frequency * frequency * 2.5 / denominator
        if score > 0:
            scores.append((score, index))
    scores.sort(key=lambda entry: entry[0], reverse=True)
    return [
        {
            "item_id": str(items[index].get("item_id", "")),
            "object_key": items[index].get("object_key", ""),
            "retrieval_text": items[index].get("retrieval_text", ""),
        }
        for _, index in scores[:limit]
    ]


def retrieve_bm25_results(query, enriched_path, limit=2):
    """使用标准库 BM25 检索本地增强 JSONL。"""
    if not 1 <= limit <= 5:
        raise ValueError("limit 必须在 1 到 5 之间")
    return _rank_bm25_items(query, _load_enriched_items(enriched_path), limit)


def apply_metadata_rule_weights(query, fused_results, metadata_items):
    """按保守 metadata 子串匹配给融合结果增加轻量规则分。"""
    query_text = str(query or "").casefold()
    metadata_by_id = {
        str(item.get("item_id", "")): item for item in metadata_items
    }
    weighted = []
    for result in fused_results:
        metadata = metadata_by_id.get(str(result["item_id"]), {})
        matched_fields = []
        rule_score = 0.0
        for field, weight in RULE_FIELDS:
            raw_value = metadata.get(field)
            values = raw_value if isinstance(raw_value, list) else [raw_value]
            if any(
                len(value_text) >= 2 and value_text.casefold() in query_text
                for value in values
                if value is not None
                for value_text in [str(value).strip()]
            ):
                matched_fields.append(field)
                rule_score += weight
        item = dict(result)
        item.update(
            {
                "rule_score": rule_score,
                "adjusted_score": result["rrf_score"] + rule_score,
                "matched_fields": matched_fields,
            }
        )
        weighted.append(item)
    return sorted(
        weighted,
        key=lambda item: (item["adjusted_score"], item["rrf_score"]),
        reverse=True,
    )


def _normalize_chroma_results(results):
    """校验并归一化 Chroma 单查询二维返回结构。"""
    rows = []
    for field in ("ids", "documents", "metadatas"):
        value = results.get(field)
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], list):
            raise ValueError(f"Chroma {field} 必须是单查询二维列表")
        rows.append(value[0])
    ids, documents, metadatas = rows
    if not (len(ids) == len(documents) == len(metadatas)):
        raise ValueError("Chroma ids、documents、metadatas 长度必须一致")

    normalized = []
    for chroma_id, document, metadata in zip(ids, documents, metadatas):
        if not isinstance(metadata, dict):
            raise ValueError("Chroma metadata 必须是字典")
        item_id = str(metadata.get("item_id", ""))
        if not item_id or item_id != str(chroma_id):
            raise ValueError("metadata item_id 必须与 Chroma id 相同")
        normalized.append(
            {
                "item_id": item_id,
                "object_key": metadata.get("object_key", ""),
                "retrieval_text": document or metadata.get("retrieval_text", ""),
            }
        )
    return normalized


def retrieve_polyvore_query(
    query,
    chroma_client,
    text_embeddings,
    image_embeddings,
    limit=2,
    enriched_path=None,
):
    """查询两个向量 collection，并按需加入 BM25 后返回 RRF 结果。"""
    if not 1 <= limit <= 5:
        raise ValueError("limit 必须在 1 到 5 之间")
    text_collection = chroma_client.get_collection(name=TEXT_COLLECTION_NAME)
    image_collection = chroma_client.get_collection(name=IMAGE_COLLECTION_NAME)
    text_raw = text_collection.query(
        query_embeddings=[text_embeddings.embed_query(query)],
        n_results=limit,
    )
    image_raw = image_collection.query(
        query_embeddings=[image_embeddings.embed_query(query)],
        n_results=limit,
    )
    metadata_items = (
        _load_enriched_items(enriched_path) if enriched_path is not None else []
    )
    fused_results = fuse_ranked_results(
        _normalize_chroma_results(text_raw),
        _normalize_chroma_results(image_raw),
        bm25_results=(
            _rank_bm25_items(query, metadata_items, limit)
            if enriched_path is not None
            else None
        ),
    )
    return apply_metadata_rule_weights(query, fused_results, metadata_items)

