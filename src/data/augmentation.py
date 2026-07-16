"""数据增强 Chain — qwen-vl-max JSON 增强 + qwen-max 营销文案生成（异步并发版）"""
import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict

from PIL import Image

from src.config import QWEN_VL_MAX, QWEN_MAX
from src.llm.dashscope_client import (
    describe_image_async,
    build_chat_llm,
    chat_async,
)

IMAGES_DIR = Path("data/raw/images")
# 百炼默认单用户 QPS 限制，并发数略低于限制留余地
MAX_CONCURRENT = 8

JSON_AUGMENT_PROMPT = """你是一个专业的时尚商品分析专家。请仔细观察这张商品图片，提取以下信息并以 JSON 格式返回。

返回格式（只返回 JSON，不要任何其他文字）：
{
    "image_summary": "商品的详细视觉描述，包括款式、颜色、材质、图案、细节特征",
    "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"]
}

要求：
1. image_summary 用中文，50-100 字
2. tags 包含风格、季节、场合、面料等维度，至少 5 个标签
3. 只返回 JSON"""

DESC_AUGMENT_PROMPT = """你是一个电商营销文案专家。根据以下商品信息，撰写一段吸引人的营销文案。

商品类型：{type}
商品名称：{name}
图片描述：{image_summary}
特征标签：{tags}

要求：
1. 50-80 字中文营销文案
2. 突出卖点，风格时尚自然
3. 只返回文案本身"""


def _extract_json(text: str) -> dict:
    """从 qwen-vl-max 返回文本中正则提取 JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pat in [r'```json\s*([\s\S]*?)\s*```', r'```\s*([\s\S]*?)\s*```', r'\{[\s\S]*\}']:
        m = re.search(pat, text)
        if m:
            try:
                return json.loads(m.group(1) if pat.startswith('```') else m.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"无法提取 JSON: {text[:200]}")


async def _augment_one(product: Dict, index: int, sem: asyncio.Semaphore) -> Dict:
    """并发处理单条商品，信号量控制并发数"""
    async with sem:
        try:
            img: Image.Image = product["image"]
            # 图片存盘
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            image_path = str(IMAGES_DIR / f"product_{index}.jpg")
            img.save(image_path, format="JPEG", quality=85)

            # 步骤1: qwen-vl-max JSON 增强
            raw_json = await describe_image_async(img, prompt=JSON_AUGMENT_PROMPT, model=QWEN_VL_MAX)
            structured = _extract_json(raw_json)

            # 步骤2: qwen-max 营销文案生成
            llm = build_chat_llm(model=QWEN_MAX, temperature=0.8)
            desc_text = await chat_async(llm, DESC_AUGMENT_PROMPT.format(
                type=product["type"],
                name=product["name"],
                image_summary=structured.get("image_summary", ""),
                tags=", ".join(structured.get("tags", [])),
            ))

            product.update({
                "image_path": image_path,
                "image_summary": structured.get("image_summary", ""),
                "tags": structured.get("tags", []),
                "description": desc_text,
            })
            return product

        except Exception as e:
            print(f"  [{index}] 增强失败: {e}")
            return product  # 降级保留原始数据


async def augment_batch(
    products: List[Dict],
    max_concurrent: int = MAX_CONCURRENT,
) -> List[Dict]:
    """
    异步并发数据增强。
    max_concurrent 控制同时进行的请求数，略低于百炼 QPS 限制。
    200 条约 2-3 分钟完成。
    """
    total = len(products)
    sem = asyncio.Semaphore(max_concurrent)
    completed = 0

    async def _tracked(idx: int, product: Dict) -> Dict:
        nonlocal completed
        result = await _augment_one(product, idx, sem)
        completed += 1
        if completed % 20 == 0 or completed == total:
            print(f"  进度: {completed}/{total}")
        return result

    tasks = [_tracked(i, p) for i, p in enumerate(products)]
    results = await asyncio.gather(*tasks)
    return list(results)


# === 同步入口（供外部调用） ===

def run_augmentation(products: List[Dict]) -> List[Dict]:
    """同步入口：在事件循环中运行异步增强"""
    return asyncio.run(augment_batch(products))


def save_augmented(products: List[Dict], output_dir: str = "data/processed"):
    """保存增强结果到 JSON，过滤 PIL Image"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    serializable = []
    for p in products:
        serializable.append({k: v for k, v in p.items() if k != "image"})

    output_path = Path(output_dir) / "products_enhanced.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"增强结果已保存: {output_path}")


def load_augmented(input_path: str = "data/processed/products_enhanced.json") -> List[Dict]:
    """从 JSON 文件加载增强结果"""
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)
