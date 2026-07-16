"""数据集加载 & 预处理"""
import random
from typing import List, Dict

from datasets import load_dataset
from PIL import Image

from src.config import DATASET_NAME, SAMPLE_SIZE


def load_kream_dataset(
    sample_size: int = SAMPLE_SIZE,
    seed: int = 42,
) -> List[Dict]:
    """
    流式加载 Kream Product BLIP Captions 数据集。
    只下载采样所需的 N 条，不拉取全部 14,904 张图片。
    返回商品列表，每条包含 image / text / type / name / summary。
    """
    # 流式加载 + 随机采样
    ds = load_dataset(DATASET_NAME, split="train", streaming=True)
    shuffled = ds.shuffle(seed=seed, buffer_size=1000)
    samples = list(shuffled.take(sample_size))

    products = []
    for item in samples:
        img: Image.Image = item["image"]
        raw_text: str = item["text"]

        # 原始 text 格式: "type, name, summary"
        parts = raw_text.split(", ", 2)
        ptype = parts[0] if len(parts) > 0 else ""
        name = parts[1] if len(parts) > 1 else ""
        summary = parts[2] if len(parts) > 2 else ""

        # 图片缩放到 50% 减少内存/算力消耗
        w, h = img.size
        img = img.resize((w // 2, h // 2), Image.LANCZOS)

        products.append({
            "image": img,
            "text": raw_text,
            "type": ptype,
            "name": name,
            "summary": summary,
        })

    return products
