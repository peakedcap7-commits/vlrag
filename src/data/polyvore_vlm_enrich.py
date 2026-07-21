import argparse
import csv
import json
import re
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.config import QWEN_VL_MAX
from src.data.minio_client import create_minio_client
from src.llm.polyvore_vlm_prompt import build_polyvore_vlm_prompt


DEFAULT_MANIFEST_PATH = Path(
    r"D:\pj\vlrag\shopping-qna\data\processed\polyvore_items_sample.jsonl"
)
DEFAULT_METADATA_PATH = Path(
    r"D:\datasets\polyvore-outfits\polyvore_item_metadata.json"
)
DEFAULT_CATEGORIES_PATH = Path(r"D:\datasets\polyvore-outfits\categories.csv")
DEFAULT_OUTPUT_PATH = Path(
    r"D:\pj\vlrag\shopping-qna\data\processed\polyvore_items_enriched_sample.jsonl"
)
VLM_FIELDS = {
    "item_id",
    "category",
    "sub_category",
    "colors",
    "material",
    "style",
    "details",
    "scene",
    "retrieval_text",
    "confidence",
    "uncertain_fields",
}
STRING_FIELDS = {"item_id", "category", "sub_category", "material", "retrieval_text"}
STRING_LIST_FIELDS = {"colors", "style", "details", "scene", "uncertain_fields"}
FORBIDDEN_RETRIEVAL_CLAIMS = (
    "防水",
    "防风",
    "透气",
    "保暖",
    "速干",
    "抗皱",
    "真皮",
    "棉质",
    "镀金",
    "塑料",
    "品牌",
    "价格",
)


def _read_categories(path):
    """读取无表头分类文件并按分类编号建立映射。"""
    with Path(path).open(encoding="utf-8", newline="") as file:
        return {row[0]: row[1] for row in csv.reader(file) if len(row) >= 2}


def _read_minio_image(client, bucket, object_key):
    """从 MinIO 读取图片并释放连接。"""
    response = client.get_object(bucket, object_key)
    try:
        return Image.open(BytesIO(response.read())).convert("RGB")
    finally:
        response.close()
        response.release_conn()


def _extract_json(text):
    """解析 VLM 返回的纯 JSON 或代码块 JSON。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"无法提取 JSON：{text[:200]}")


def _validate_vlm_result(result):
    """严格校验 VLM 返回的十一字段 JSON。"""
    if not isinstance(result, dict) or set(result) != VLM_FIELDS:
        raise ValueError("VLM 结果必须恰好包含约定的十一字段")
    if any(not isinstance(result[field], str) for field in STRING_FIELDS):
        raise ValueError("VLM 字符串字段类型错误")
    if any(
        not isinstance(result[field], list)
        or any(not isinstance(value, str) for value in result[field])
        for field in STRING_LIST_FIELDS
    ):
        raise ValueError("VLM 字符串列表字段类型错误")
    confidence = result["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("confidence 必须是 0 到 1 之间的数值")
    if not re.search(r"[\u4e00-\u9fff]", result["retrieval_text"]):
        raise ValueError("retrieval_text 必须包含中文字符")
    if result["material"]:
        raise ValueError("material 必须为空字符串")
    if "material" not in result["uncertain_fields"]:
        raise ValueError("uncertain_fields 必须包含 material")
    if any(
        claim in result["retrieval_text"] for claim in FORBIDDEN_RETRIEVAL_CLAIMS
    ):
        raise ValueError("retrieval_text 包含无依据的功能或材质声明")
    return result


def enrich_polyvore_sample(
    manifest_path=DEFAULT_MANIFEST_PATH,
    metadata_path=DEFAULT_METADATA_PATH,
    categories_path=DEFAULT_CATEGORIES_PATH,
    output_path=DEFAULT_OUTPUT_PATH,
    limit=5,
    client=None,
):
    """使用 qwen-vl-max 增强最多五条 Polyvore 商品。"""
    if not 1 <= limit <= 5:
        raise ValueError("limit 必须在 1 到 5 之间")

    manifest = [
        json.loads(line)
        for line in Path(manifest_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][:limit]
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    categories = _read_categories(categories_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    client = client or create_minio_client()
    from src.llm.dashscope_client import describe_image

    with output_path.open("w", encoding="utf-8") as output_file:
        for record in manifest:
            item_id = str(record["item_id"])
            item_metadata = metadata.get(item_id, {})
            prompt_metadata = {
                "item_id": item_id,
                "url_name": item_metadata.get("url_name", ""),
                "semantic_category": item_metadata.get("semantic_category", ""),
                "category_name": categories.get(
                    str(item_metadata.get("category_id", "")), ""
                ),
                "bucket": record["bucket"],
                "object_key": record["object_key"],
            }
            image = _read_minio_image(
                client, record["bucket"], record["object_key"]
            )
            result = _validate_vlm_result(
                _extract_json(
                    describe_image(
                        image,
                        prompt=build_polyvore_vlm_prompt(prompt_metadata),
                        model=QWEN_VL_MAX,
                    )
                )
            )
            output_file.write(
                json.dumps({**result, **record}, ensure_ascii=False) + "\n"
            )

    return {"enriched": len(manifest), "path": str(output_path)}


def _parse_limit(value):
    """限制 smoke enrich 只能处理一到五条。"""
    limit = int(value)
    if not 1 <= limit <= 5:
        raise argparse.ArgumentTypeError("limit 必须在 1 到 5 之间")
    return limit


def main():
    parser = argparse.ArgumentParser(description="执行 Polyvore VLM 小样本增强")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--categories", type=Path, default=DEFAULT_CATEGORIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=_parse_limit, default=5)
    args = parser.parse_args()

    result = enrich_polyvore_sample(
        manifest_path=args.manifest,
        metadata_path=args.metadata,
        categories_path=args.categories,
        output_path=args.output,
        limit=args.limit,
    )
    print(f"增强条数：{result['enriched']}，文件路径：{result['path']}")


if __name__ == "__main__":
    main()
