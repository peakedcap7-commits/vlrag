"""
全流程 Pipeline：M1 数据加载 → M2 数据增强 → M3 向量库 → M4/M5 检索验证
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path

# ===== M1: 数据加载 =====
print("=" * 50)
print("M1: 数据加载")
print("=" * 50)

from src.data.loader import load_kream_dataset
from src.config import SAMPLE_SIZE

products = load_kream_dataset(sample_size=SAMPLE_SIZE, seed=42)
print(f"加载完成: {len(products)} 条商品")
print(f"示例: [{products[0]['type']}] {products[0]['name']}")
print(f"图片尺寸: {products[0]['image'].size}")

# ===== M2: 数据增强 =====
print()
print("=" * 50)
print("M2: 数据增强 (qwen-vl-max + qwen-max) [异步并发]")
print(f"注意: 将处理 {SAMPLE_SIZE} 条，并发数=8，约 2-3 分钟")
print("=" * 50)

from src.data.augmentation import run_augmentation, save_augmented

products = run_augmentation(products)
save_augmented(products)

print(f"增强完成: {len(products)} 条")
print(f"第一条 tags: {products[0].get('tags', [])}")
print(f"image_path: {products[0].get('image_path', 'N/A')}")

# 验证图片已存盘
img_dir = Path("data/raw/images")
img_count = len(list(img_dir.glob("*.jpg")))
print(f"图片存盘: {img_count} 张 → {img_dir}")

print()
print("M1 + M2 完成!")
